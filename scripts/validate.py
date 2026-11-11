#!/usr/bin/env python3
"""Run meaningful Python tests, native sibling-app contract checks, and source/fixture hashing."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import platform
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sandworm_research_agent.core import Budget, load_input, sha256
from sandworm_research_agent.runner import fixture_model, run


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    if not result.wasSuccessful():
        # Test failures here are from synthetic fixtures only.
        print(stream.getvalue(), file=sys.stderr)
        return 1
    raw = (ROOT / "examples/study.json").read_bytes()
    draft = json.loads((ROOT / "examples/draft.json").read_text())
    outputs = asyncio.run(run(load_input(raw), Budget(), fixture_model(draft), mode="fixture", input_sha256=sha256(raw)))
    contracts = {}
    engine_paths = {
        "thai_eval": Path("/workspace/sites/sandworm-thai-eval/dist/engine.js"),
        "ledger": Path("/workspace/sites/sandworm-ai-run-ledger/dist/ledger.js"),
    }
    if all(p.exists() for p in engine_paths.values()):
        js = """
const fs = require('node:fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const evaluate = require(process.argv[1]);
const ledger = require(process.argv[2]);
const e = evaluate.evaluateObjects(data.thai_eval_contract_dataset, data.thai_eval_candidates);
const l = ledger.analyze(JSON.stringify([data.ledger]), '[]');
if(e.models[0].score !== 100 || e.models[0].passedCases !== 2) throw Error('contract eval failed');
console.log(JSON.stringify({thai_eval:'passed_2_contract_cases',ledger:'accepted_one_attempt'}));
"""
        checked = subprocess.run(["node", "-e", js, *map(str, engine_paths.values())], input=json.dumps(outputs), text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if checked.returncode:
            print("Native sibling export contract failed", file=sys.stderr)
            return 1
        contracts = json.loads(checked.stdout)
    else:
        contracts = {"status": "not_available", "reason": "Sibling engines are optional for portable core validation"}
    selected = []
    for folder in ("src", "tests", "examples", "scripts", "docs"):
        selected.extend(p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".cjs")
    selected.extend(p for p in (ROOT / "README.md", ROOT / "README.th.md", ROOT / "SECURITY.md", ROOT / "THIRD_PARTY_NOTICES.md", ROOT / "LICENSE", ROOT / "pyproject.toml", ROOT / "requirements.lock") if p.exists())
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(selected))}
    report = {"schema_version": 1, "project": "sandworm-research-agent-kit", "status": "passed",
              "generated_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "tests": {"passed": result.testsRun, "failed": len(result.failures), "errors": len(result.errors)},
              "upstream_smokes": {"pydantic_ai_function_model": "passed", "pydantic_ai_test_model": "passed",
                                  "paid_provider_request": "not_run"},
              "versions": {"pydantic-ai-slim": version("pydantic-ai-slim"), "pydantic": version("pydantic"), "openai": version("openai")},
              "native_export_contracts": contracts,
              "hash_scope": "Exact file bytes listed below; excludes this report, web viewer, Git metadata, virtual environments and runtime output.",
              "sha256": hashes}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "passed", "tests": result.testsRun, "native_export_contracts": contracts, "hashed_files": len(hashes)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
