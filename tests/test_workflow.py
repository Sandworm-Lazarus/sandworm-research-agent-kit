from __future__ import annotations

import asyncio
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from sandworm_research_agent.cli import main, read_bounded
from sandworm_research_agent.core import Budget, MAX_BYTES, ResearchDraft, ResearchError, exports, load_input, plan, review, sha256, strict_json
from sandworm_research_agent.runner import fixture_model, openai_responses_model, run

ROOT = Path(__file__).resolve().parents[1]
RAW = (ROOT / "examples/study.json").read_bytes()
DRAFT = json.loads((ROOT / "examples/draft.json").read_text())


class InputTests(unittest.TestCase):
    def test_thai_input_preserved(self):
        self.assertIn("กิลด์", load_input(RAW).sources[0].text)

    def test_boolean_schema_version_not_coerced(self):
        d = json.loads(RAW); d["schema_version"] = True
        with self.assertRaises(ResearchError):
            load_input(json.dumps(d).encode())

    def test_duplicate_json_key_rejected(self):
        with self.assertRaisesRegex(ResearchError, "DUPLICATE_JSON_KEY"):
            strict_json(b'{"key":1,"key":2}')

    def test_nonfinite_json_rejected(self):
        with self.assertRaises(ResearchError):
            strict_json(b'{"key":NaN}')

    def test_non_utf8_rejected(self):
        with self.assertRaises(ResearchError):
            strict_json(b'\xff')

    def test_limit_rejected(self):
        with self.assertRaisesRegex(ResearchError, "INPUT_TOO_LARGE"):
            strict_json(b' ' * (MAX_BYTES + 1))

    def test_duplicate_source_rejected(self):
        d = json.loads(RAW); d["sources"].append(d["sources"][0])
        with self.assertRaisesRegex(ResearchError, "INVALID_INPUT_SCHEMA"):
            load_input(json.dumps(d).encode())

    def test_duplicate_question_rejected(self):
        d = json.loads(RAW); d["questions"].append(d["questions"][0])
        with self.assertRaises(ResearchError):
            load_input(json.dumps(d).encode())

    def test_unknown_source_rejected(self):
        d = json.loads(RAW); d["questions"][0]["source_ids"] = ["missing"]
        with self.assertRaises(ResearchError):
            load_input(json.dumps(d).encode())

    def test_url_credentials_rejected(self):
        for url in ["https://user:secret@example.invalid/x", "https://example.invalid/?key=secret", "file:///etc/passwd", "https://example.invalid/#secret", "https://example.invalid/\n"]:
            d = json.loads(RAW); d["sources"][0]["url"] = url
            with self.subTest(url=url), self.assertRaises(ResearchError):
                load_input(json.dumps(d).encode())

    def test_string_boolean_not_coerced(self):
        d = copy.deepcopy(DRAFT); d["rows"][0]["unknown"] = "false"
        with self.assertRaises(Exception):
            ResearchDraft.model_validate(d)

    def test_extra_claim_url_rejected(self):
        d = copy.deepcopy(DRAFT); d["rows"][0]["source_url"] = "https://invented.invalid"
        with self.assertRaises(Exception):
            ResearchDraft.model_validate(d)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.study = load_input(RAW)

    def check_error(self, draft, code):
        with self.assertRaisesRegex(ResearchError, code):
            review(self.study, ResearchDraft.model_validate(draft))

    def test_supported_and_unknown(self):
        rows = review(self.study, ResearchDraft.model_validate(DRAFT))
        self.assertEqual(rows[0]["region"], "TH-synthetic")
        self.assertEqual(rows[1]["claim"], "NR")
        self.assertIsNone(rows[1]["source_url"])

    def test_missing_answer_rejected(self):
        self.check_error({"rows": DRAFT["rows"][:1]}, "QUESTION_COVERAGE_INVALID")

    def test_duplicate_answer_rejected(self):
        self.check_error({"rows": [DRAFT["rows"][0]] * 2}, "QUESTION_COVERAGE_INVALID")

    def test_out_of_scope_source_rejected(self):
        d = copy.deepcopy(DRAFT); d["rows"][0]["source_id"] = "jp-guide-01"
        self.check_error(d, "SOURCE_OUT_OF_SCOPE")

    def test_invented_source_rejected(self):
        d = copy.deepcopy(DRAFT); d["rows"][0]["source_id"] = "invented"
        self.check_error(d, "SOURCE_OUT_OF_SCOPE")

    def test_hallucinated_number_rejected(self):
        d = copy.deepcopy(DRAFT); d["rows"][0]["claim"] = d["rows"][0]["excerpt"] = "ใช้เหรียญ 999 เหรียญ"
        self.check_error(d, "EVIDENCE_NOT_EXTRACTIVE")

    def test_paraphrase_rejected_even_with_valid_quote(self):
        d = copy.deepcopy(DRAFT); d["rows"][0]["claim"] = "สร้างกิลด์ราคา 100"
        self.check_error(d, "EVIDENCE_NOT_EXTRACTIVE")

    def test_unknown_must_not_cite(self):
        d = copy.deepcopy(DRAFT); d["rows"][1]["source_id"] = "jp-guide-01"
        self.check_error(d, "UNKNOWN_ROW_INVALID")

    def test_unknown_must_say_nr(self):
        d = copy.deepcopy(DRAFT); d["rows"][1]["claim"] = "น่าจะ 10%"
        self.check_error(d, "UNKNOWN_ROW_INVALID")

    def test_null_excerpt_rejected(self):
        d = copy.deepcopy(DRAFT); d["rows"][0]["excerpt"] = None
        self.check_error(d, "EVIDENCE_NOT_EXTRACTIVE")

    def test_plan_has_no_extra_source_scope(self):
        self.assertEqual(plan(self.study)["requests"], 1)
        self.assertEqual(plan(self.study)["questions"][0]["source_ids"], ["th-guide-01"])


class NativeAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_function_model_smoke(self):
        result = await run(load_input(RAW), Budget(), fixture_model(DRAFT), mode="fixture", input_sha256=sha256(RAW))
        self.assertEqual(result["report"]["summary"], {"questions": 2, "supported": 1, "unknown": 1, "requests": 1})
        self.assertGreater(result["ledger"]["input_tokens"], 0)

    async def test_actual_test_model_smoke(self):
        result = await run(load_input(RAW), Budget(), TestModel(custom_output_args=DRAFT), mode="fixture", input_sha256=sha256(RAW))
        self.assertEqual(result["report"]["mode"], "fixture")

    async def test_malicious_model_output_reviewed(self):
        d = copy.deepcopy(DRAFT); d["rows"][0]["claim"] = "untrusted change"
        with self.assertRaisesRegex(ResearchError, "EVIDENCE_NOT_EXTRACTIVE"):
            await run(load_input(RAW), Budget(), fixture_model(d), mode="fixture", input_sha256=sha256(RAW))

    async def test_budget_denied_before_function_called(self):
        calls = []
        def response(messages, info):
            calls.append(1)
            raise RuntimeError("should never execute")
        with self.assertRaisesRegex(ResearchError, "BUDGET_INSUFFICIENT"):
            await run(load_input(RAW), Budget(max_cost_usd="0"), FunctionModel(response), mode="fixture", input_sha256=sha256(RAW))
        self.assertEqual(calls, [])

    async def test_raw_model_error_hidden(self):
        def response(messages, info):
            raise RuntimeError("SOURCE SECRET api-key-value test@example.invalid")
        with self.assertRaises(ResearchError) as error:
            await run(load_input(RAW), Budget(), FunctionModel(response), mode="fixture", input_sha256=sha256(RAW))
        self.assertEqual(str(error.exception), "MODEL_OR_LIMIT_FAILURE")

    async def test_token_limit_fails(self):
        study = load_input(RAW)
        study.sources[0].text += " repeated synthetic context" * 1000
        with self.assertRaisesRegex(ResearchError, "MODEL_OR_LIMIT_FAILURE"):
            await run(study, Budget(max_input_tokens=256), fixture_model(DRAFT), mode="fixture", input_sha256=sha256(RAW))

    async def test_export_contracts_no_raw_source_text(self):
        result = await run(load_input(RAW), Budget(), fixture_model(DRAFT), mode="fixture", input_sha256=sha256(RAW))
        self.assertEqual(result["thai_eval_candidates"]["models"][0]["outputs"][1]["abstained"], True)
        self.assertEqual(set(result["ledger"]), {"id", "model", "input_tokens", "output_tokens", "latency_ms", "status", "retry"})
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("No numeric pet growth rates", serialized)


class CliTests(unittest.TestCase):
    def test_unknown_arguments_do_not_echo_values(self):
        with redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()) as out:
            code = main([str(ROOT / "examples/study.json"), "--fixture-draft", str(ROOT / "examples/draft.json"),
                         "--output", "output/test", "--unexpected", "REVIEW_SECRET_SENTINEL"])
        self.assertEqual(code, 2)
        self.assertEqual(err.getvalue().strip(), '{"error": "INVALID_ARGUMENTS"}')
        self.assertNotIn("REVIEW_SECRET_SENTINEL", err.getvalue() + out.getvalue())

    def test_missing_arguments_are_sanitized(self):
        with redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()) as out:
            code = main(["REVIEW_PRIVATE_SOURCE_PATH"])
        self.assertEqual(code, 2)
        self.assertEqual(err.getvalue().strip(), '{"error": "INVALID_ARGUMENTS"}')
        self.assertNotIn("REVIEW_PRIVATE_SOURCE_PATH", err.getvalue() + out.getvalue())

    def test_rejected_live_model_value_is_not_echoed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"OPENAI_API_KEY": "synthetic-test-key"}), \
                redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()) as out:
            code = main([str(ROOT / "examples/study.json"), "--live", "--model", "https://REVIEW_SECRET_SENTINEL.invalid/api",
                         "--budget", str(ROOT / "examples/budget.json"), "--output", str(Path(tmp)/"out")])
        self.assertEqual(code, 2)
        self.assertEqual(err.getvalue().strip(), '{"error": "INVALID_MODEL_NAME"}')
        self.assertNotIn("REVIEW_SECRET_SENTINEL", err.getvalue() + out.getvalue())

    def test_fixture_cli_exports(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            out = str(Path(tmp) / "new")
            self.assertEqual(main([str(ROOT / "examples/study.json"), "--fixture-draft", str(ROOT / "examples/draft.json"), "--output", out]), 0)
            self.assertEqual(len(list(Path(out).glob("*"))), 4)

    def test_cli_error_hides_original(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(io.StringIO()) as err:
            bad = Path(tmp) / "input.json"; bad.write_text('{"private":"TOP-SECRET", invalid}')
            code = main([str(bad), "--fixture-draft", str(ROOT / "examples/draft.json"), "--output", str(Path(tmp)/"out")])
            self.assertEqual(code, 2)
            self.assertNotIn("TOP-SECRET", err.getvalue())

    def test_cli_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(io.StringIO()) as err:
            code = main([str(ROOT / "examples/study.json"), "--fixture-draft", str(ROOT / "examples/draft.json"), "--output", tmp])
            self.assertEqual(code, 2)
            self.assertIn("OUTPUT_EXISTS", err.getvalue())

    def test_live_needs_explicit_config(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(io.StringIO()) as err:
            code = main([str(ROOT / "examples/study.json"), "--live", "--output", str(Path(tmp)/"out")])
            self.assertEqual(code, 2)
            self.assertIn("LIVE_CONFIGURATION_REQUIRED", err.getvalue())

    def test_bad_model_name_rejected_before_client(self):
        with self.assertRaisesRegex(ResearchError, "INVALID_MODEL_NAME"):
            openai_responses_model("https://untrusted.invalid/api", "not-real")

    def test_missing_input_sanitized(self):
        with self.assertRaisesRegex(ResearchError, "INPUT_READ_FAILURE"):
            read_bounded("/no-such-sensitive-file")

    def test_source_hash_exact_bytes(self):
        self.assertNotEqual(sha256(RAW), sha256(RAW + b"\n"))


if __name__ == "__main__":
    unittest.main()
