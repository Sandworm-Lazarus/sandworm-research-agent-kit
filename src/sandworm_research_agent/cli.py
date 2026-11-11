from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .core import Budget, MAX_BYTES, ResearchDraft, ResearchError, load_input, sha256, strict_json
from .runner import fixture_model, openai_responses_model, run


class PrivateArgumentParser(argparse.ArgumentParser):
    """Argument errors must not echo untrusted values, paths or flags."""

    def error(self, message):
        raise ResearchError("INVALID_ARGUMENTS")


def read_bounded(path: str, limit: int = MAX_BYTES) -> bytes:
    try:
        with open(path, "rb") as stream:
            raw = stream.read(limit + 1)
    except Exception:
        raise ResearchError("INPUT_READ_FAILURE") from None
    if len(raw) > limit:
        raise ResearchError("INPUT_TOO_LARGE")
    return raw


def main(argv=None) -> int:
    parser = PrivateArgumentParser(description="Evidence-bound research, URLs never fetched", allow_abbrev=False)
    parser.add_argument("input")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture-draft", help="Synthetic draft passed through a real Pydantic AI FunctionModel; no network")
    mode.add_argument("--live", action="store_true", help="One OpenAI Responses request; sends supplied source text")
    parser.add_argument("--model", help="Explicit OpenAI model for --live")
    parser.add_argument("--budget", help="Budget JSON; required in live mode")
    parser.add_argument("--output", required=True, help="New output directory (must not exist)")
    try:
        args = parser.parse_args(argv)
        raw = read_bounded(args.input)
        study = load_input(raw)
        budget = Budget.model_validate(strict_json(read_bounded(args.budget))) if args.budget else Budget()
        if args.live:
            if not args.model or not args.budget or not os.environ.get("OPENAI_API_KEY"):
                raise ResearchError("LIVE_CONFIGURATION_REQUIRED")
            model = openai_responses_model(args.model, os.environ["OPENAI_API_KEY"])
        else:
            draft = ResearchDraft.model_validate(strict_json(read_bounded(args.fixture_draft, 65536)))
            model = fixture_model(draft.model_dump())
        if Path(args.output).exists():
            raise ResearchError("OUTPUT_EXISTS")
        results = asyncio.run(run(study, budget, model, mode="live" if args.live else "fixture", input_sha256=sha256(raw)))
        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=False)
        for name in ("report", "thai_eval_candidates", "thai_eval_contract_dataset"):
            (out / f"{name}.json").write_text(json.dumps(results[name], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (out / "ledger.jsonl").write_text(json.dumps(results["ledger"], ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": "ok", "mode": results["report"]["mode"], "questions": len(study.questions)}))
        return 0
    except ResearchError as exc:
        print(json.dumps({"error": exc.code}), file=sys.stderr)
        return 2
    except Exception:
        print('{"error":"INVALID_CONFIGURATION_OR_IO"}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
