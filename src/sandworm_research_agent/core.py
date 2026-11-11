"""Pure validation and export. Source URLs are identifiers: this module never fetches them."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_BYTES = 524288
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]


class ResearchError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Source(StrictModel):
    id: Identifier
    url: Annotated[str, Field(max_length=2048)]
    region: Annotated[str, Field(min_length=1, max_length=64)]
    version: Annotated[str, Field(min_length=1, max_length=128)]
    text: Annotated[str, Field(min_length=1, max_length=32768)]

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        p = urlsplit(value)
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError("HTTPS source identifier without credentials/query/fragment required")
        if any(ord(c) < 33 for c in value) or "\\" in value:
            raise ValueError("invalid URL identifier")
        return value


class Question(StrictModel):
    id: Identifier
    question: Annotated[str, Field(min_length=1, max_length=1024)]
    source_ids: Annotated[list[Identifier], Field(min_length=1, max_length=16)]

    @field_validator("source_ids")
    @classmethod
    def unique_sources(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate source id")
        return value


class ResearchInput(StrictModel):
    schema_version: Literal[1]
    study_id: Identifier
    sources: Annotated[list[Source], Field(min_length=1, max_length=64)]
    questions: Annotated[list[Question], Field(min_length=1, max_length=32)]

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("integer schema version 1 required")
        return value

    @model_validator(mode="after")
    def references(self):
        source_ids = {s.id for s in self.sources}
        if len(source_ids) != len(self.sources) or len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("duplicate identity")
        if any(not set(q.source_ids) <= source_ids for q in self.questions):
            raise ValueError("missing source identity")
        return self


class DraftRow(StrictModel):
    question_id: Identifier
    unknown: bool
    claim: Annotated[str, Field(min_length=1, max_length=1024)]
    source_id: Identifier | None
    excerpt: Annotated[str, Field(max_length=1024)] | None


class ResearchDraft(StrictModel):
    rows: Annotated[list[DraftRow], Field(min_length=1, max_length=32)]


class Budget(StrictModel):
    max_input_tokens: Annotated[int, Field(ge=256, le=131072)] = 32768
    max_output_tokens: Annotated[int, Field(ge=128, le=16384)] = 4096
    max_cost_usd: Annotated[str, Field(max_length=24, pattern=r"^(0|[1-9][0-9]*)(\.[0-9]{1,8})?$")] = "0.10"
    input_usd_per_million: Annotated[str, Field(max_length=24, pattern=r"^(0|[1-9][0-9]*)(\.[0-9]{1,8})?$")] = "1.00"
    output_usd_per_million: Annotated[str, Field(max_length=24, pattern=r"^(0|[1-9][0-9]*)(\.[0-9]{1,8})?$")] = "5.00"
    timeout_seconds: Annotated[int, Field(ge=1, le=120)] = 30

    def reserve(self) -> str:
        reservation = (Decimal(self.max_input_tokens) * Decimal(self.input_usd_per_million)
                       + Decimal(self.max_output_tokens) * Decimal(self.output_usd_per_million)) / Decimal(1000000)
        if reservation > Decimal(self.max_cost_usd):
            raise ResearchError("BUDGET_INSUFFICIENT")
        return str(reservation)


def strict_json(raw: bytes, limit: int = MAX_BYTES):
    if len(raw) > limit:
        raise ResearchError("INPUT_TOO_LARGE")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ResearchError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ResearchError("INVALID_JSON")))
    except ResearchError:
        raise
    except Exception:
        raise ResearchError("INVALID_JSON") from None


def load_input(raw: bytes) -> ResearchInput:
    try:
        return ResearchInput.model_validate(strict_json(raw))
    except ResearchError:
        raise
    except Exception:
        raise ResearchError("INVALID_INPUT_SCHEMA") from None


def plan(study: ResearchInput) -> dict:
    return {"stages": ["plan", "extract", "review"], "requests": 1,
            "questions": [{"id": q.id, "source_ids": q.source_ids} for q in study.questions]}


def review(study: ResearchInput, draft: ResearchDraft) -> list[dict]:
    sources = {s.id: s for s in study.sources}
    questions = {q.id: q for q in study.questions}
    row_ids = [r.question_id for r in draft.rows]
    if len(set(row_ids)) != len(row_ids) or set(row_ids) != set(questions):
        raise ResearchError("QUESTION_COVERAGE_INVALID")
    rows = []
    by_id = {r.question_id: r for r in draft.rows}
    for q in study.questions:
        row = by_id[q.id]
        if row.unknown:
            if row.claim != "NR" or row.source_id is not None or row.excerpt is not None:
                raise ResearchError("UNKNOWN_ROW_INVALID")
            rows.append({"question_id": q.id, "claim": "NR", "unknown": True,
                         "confidence": "unknown", "source_id": None, "source_url": None,
                         "region": "NR", "version": "NR", "excerpt": None})
            continue
        if row.source_id not in q.source_ids:
            raise ResearchError("SOURCE_OUT_OF_SCOPE")
        source = sources[row.source_id]
        if not row.excerpt or row.excerpt not in source.text or row.claim != row.excerpt:
            raise ResearchError("EVIDENCE_NOT_EXTRACTIVE")
        rows.append({"question_id": q.id, "claim": row.claim, "unknown": False,
                     "confidence": "source_text_match", "source_id": source.id,
                     "source_url": source.url, "region": source.region, "version": source.version,
                     "excerpt": row.excerpt})
    return rows


def exports(study: ResearchInput, rows: list[dict], usage: dict, *, mode: str, input_sha256: str,
            reservation: str) -> dict:
    candidates = {"schemaVersion": 1, "models": [{"id": "research-candidate", "outputs": [
        {"caseId": r["question_id"], "text": "ข้อมูลไม่เพียงพอ" if r["unknown"] else r["claim"],
         "citations": [] if r["unknown"] else [r["source_id"]], "abstained": r["unknown"]} for r in rows]}]}
    # Dataset checks schema/unknown/citation shape only. Humans must independently author answer-quality assertions.
    dataset = {"schemaVersion": 1, "datasetId": study.study_id, "cases": [
        {"id": q.id, "weight": 1, "assertions": {"exact": "ข้อมูลไม่เพียงพอ", "abstain": True} if rows[i]["unknown"]
         else {"citations": [rows[i]["source_id"]]}} for i, q in enumerate(study.questions)]}
    record = {"schema_version": 1, "project": "sandworm-research-agent-kit", "mode": mode,
              "generated_at": datetime.now(timezone.utc).isoformat(), "input_sha256": input_sha256,
              "summary": {"questions": len(rows), "supported": sum(not r["unknown"] for r in rows),
                          "unknown": sum(r["unknown"] for r in rows), "requests": usage["requests"]},
              "plan": plan(study), "findings": rows, "budget": {"reserved_usd_at_user_rates": reservation},
              "usage": usage, "limits": ["Extractive source matching only; source truth and question relevance require human review.",
                                          "Input source URLs are not fetched or verified.",
                                          "Exported study/source identifiers and excerpts require review before sharing."]}
    ledger = {"id": "research-attempt-1", "model": "synthetic-research-model" if mode == "fixture" else "research-model", "input_tokens": usage["input_tokens"],
              "output_tokens": usage["output_tokens"], "latency_ms": usage["latency_ms"], "status": "success", "retry": False}
    return {"report": record, "thai_eval_candidates": candidates, "thai_eval_contract_dataset": dataset,
            "ledger": ledger}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
