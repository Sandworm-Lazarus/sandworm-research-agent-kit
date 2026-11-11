# Development notes

Version 0.1.0 was implemented as an original Sandworm workflow around the official `pydantic-ai-slim[openai]` dependency, pinned to 2.67.0. The dependency environment is recorded in `requirements.lock`.

## Stages

- `core.py`: strict typed input/output schemas, duplicate-key JSON reader, source-scope planning, extractive review, provenance and export contracts.
- `runner.py`: actual Pydantic AI Agent, native usage limits, FunctionModel fixture, optional official OpenAI Responses client with SDK retries disabled and fixed base URL.
- `cli.py`: bounded file reads, fixture/live configuration, new-directory output and sanitized error codes.
- `web/`: separate report viewer added by the suite's owner; it reads reports and does not host the Python worker.

The fixture supplies answers through FunctionModel and therefore tests framework serialization, schema handling, usage accounting and our review. TestModel provides a second upstream harness smoke. Neither is a quality benchmark. Validation deliberately does not send a paid API request.

The generated Thai Eval dataset is a self-derived contract test: it must never be described as an independent benchmark. The Ledger model is aliased and repeated attempt IDs must be made unique when concatenating multiple runs. Native export contract tests use the actual sibling app engines when present; release validation includes their outcomes.

`scripts/validate.py` runs tests, records exact SHA-256 of source/tests/examples/config/docs, and identifies dependency versions. Re-run after changing those files. The report excludes itself, Git metadata, virtual environments and runtime output. No GitHub Actions pass is claimed from these local results.

Later work can add independent relevance scoring, a reviewed source collector and non-OpenAI provider adapters. Those require their own transmission, token accounting and test boundaries rather than automatically enabling new tools for the model.
