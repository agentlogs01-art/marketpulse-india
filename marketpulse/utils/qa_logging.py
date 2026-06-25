"""
utils/qa_logging.py

Structured JSON logging for each pipeline run, capturing the
PipelineRunRecord fields needed for audit/QA per the PRD's emphasis on
traceability for the SEBI entity rule (FR-02.4.2) and jargon enforcement
(FR-02.4.1): every auto-correction made by the deterministic Layer-2
enforcers must be recoverable after the fact.

Writes to stdout as a single JSON line per run (cheap, free, and
trivially captured by Railway's / GitHub Actions' log aggregation --
no paid logging service required per the infra budget).
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

from marketpulse.models.schemas import PipelineRunRecord


def log_run_record(record: PipelineRunRecord) -> None:
    payload = asdict(record)
    print(json.dumps(payload, default=str), file=sys.stdout)


def summarize_record(record: PipelineRunRecord) -> str:
    parts = [f"run_date={record.run_date_ist}"]
    if record.suppressed:
        parts.append(f"SUPPRESSED ({record.suppression_reason})")
    if record.domestic_override_active:
        parts.append("domestic_override=ACTIVE")
    if record.divergence_flag:
        parts.append("divergence=FLAGGED")
    if record.flat_override_triggered:
        parts.append("flat_override=TRIGGERED")
    parts.append(f"jargon_injections={len(record.jargon_injections)}")
    parts.append(f"entity_violations={len(record.entity_violations)}")
    return " | ".join(parts)
