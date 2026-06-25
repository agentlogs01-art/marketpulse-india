"""
pipeline/orchestrator.py

Top-level orchestration of the daily MarketPulse India run, matching the
PRD's strict IST timeline:

    06:00 IST  Pre-render  -> render static template shell
    06:45 IST  Snapshot    -> capture GIFT Nifty + instrument snapshots
    06:50 IST  Assembly    -> AI analysis, aggregation, reconciliation,
                              jargon/entity enforcement, final HTML render
    07:00 IST  Send        -> dispatch email

This module is deliberately defensive: at every stage, a failure degrades
gracefully (skip a source, fall back to neutral analysis, suppress the
run) rather than throwing and missing the 07:00 IST send — see PRD
Section 3 reliability principles and FR-02.4.2 point 3 (suppression is
preferable to a non-compliant send).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from marketpulse.ai_engine import entity_scanner, jargon_enforcer
from marketpulse.ai_engine.bias_engine import (
    aggregate_sector_scores,
    detect_domestic_override,
    reconcile_bias,
)
from marketpulse.ai_engine.llm_client import analyze_event, fallback_neutral_analysis
from marketpulse.constants.paragraph4_tokens import resolve_paragraph_4
from marketpulse.models.schemas import BIAS_PLAIN_ENGLISH, EventAnalysis, NewsEvent, PipelineRunRecord
from marketpulse.pipeline.ingestion import ingest_all_sources
from marketpulse.pipeline.market_data import (
    fetch_all_instrument_snapshots,
    fetch_gift_nifty_snapshot,
    flag_stale_snapshots,
)

# Narrative fields that must pass through both Layer-2 deterministic
# enforcers (jargon injection + entity genericization) before assembly.
NARRATIVE_FIELDS_TO_ENFORCE = [
    "one_line_summary_for_beginner",
]


def run_ai_analysis_stage(
    events: list,
) -> tuple:
    """
    FR-02.2 + FR-02.4.1 + FR-02.4.2: run sentiment analysis for every
    ingested event, then apply both deterministic Layer-2 enforcers to
    every plain-English text field produced by the LLM.
    """
    analyses: list = []
    all_jargon_injections: list = []
    all_entity_violations: list = []

    for event in events:
        try:
            analysis = analyze_event(event)
        except Exception:
            analysis = fallback_neutral_analysis(event)

        # Enforce on the top-level beginner summary.
        fields = {"one_line_summary_for_beginner": analysis.one_line_summary_for_beginner}
        fields, jargon_inj = jargon_enforcer.enforce_jargon_on_fields(
            fields, NARRATIVE_FIELDS_TO_ENFORCE
        )
        fields, entity_viol = entity_scanner.scan_fields(fields, NARRATIVE_FIELDS_TO_ENFORCE)
        analysis.one_line_summary_for_beginner = fields["one_line_summary_for_beginner"]
        all_jargon_injections.extend(jargon_inj)
        all_entity_violations.extend(entity_viol)

        # Enforce on every per-sector rationale text.
        for impact in analysis.affected_sectors:
            text, jinj = jargon_enforcer.enforce_jargon_definitions(impact.rationale_plain_english)
            text, eviol = entity_scanner.scan_and_genericize(text)
            impact.rationale_plain_english = text
            for inj in jinj:
                inj["field"] = f"sector_impact[{impact.sector.value}].rationale"
            for v in eviol:
                v["field"] = f"sector_impact[{impact.sector.value}].rationale"
            all_jargon_injections.extend(jinj)
            all_entity_violations.extend(eviol)

        analyses.append(analysis)

    return analyses, all_jargon_injections, all_entity_violations


def run_full_pipeline(prev_nifty_close: float, run_date_ist: Optional[str] = None) -> dict:
    """
    Executes the full 06:00 -> 07:00 IST pipeline in one synchronous call
    (suitable for a GitHub Actions cron trigger per the PRD's infra
    choice — Section 3 budget: GitHub Actions free tier for scheduling).

    Returns a dict bundling everything email_system/render.py needs, plus
    the PipelineRunRecord for QA/audit logging.
    """
    run_date_ist = run_date_ist or datetime.now().strftime("%Y-%m-%d")
    record = PipelineRunRecord(run_date_ist=run_date_ist)

    # --- 06:45 IST: Snapshot stage -----------------------------------
    gift_nifty = fetch_gift_nifty_snapshot(prev_nifty_close)
    instrument_snapshots = flag_stale_snapshots(fetch_all_instrument_snapshots())

    # --- Ingestion (can run any time before assembly) -----------------
    events = ingest_all_sources()
    events_by_id = {e.event_id: e for e in events}

    # --- 06:50 IST: Assembly stage --------------------------------------
    analyses, jargon_injections, entity_violations = run_ai_analysis_stage(events)
    record.jargon_injections = jargon_injections
    record.entity_violations = entity_violations

    if entity_scanner.should_suppress_run(entity_violations):
        record.suppressed = True
        record.suppression_reason = "Entity violation count exceeded safety threshold (FR-02.4.2)"
        return {"record": record, "suppressed": True}

    sector_scorecards = aggregate_sector_scores(analyses, events_by_id)
    override = detect_domestic_override(events_by_id, analyses)
    record.domestic_override_active = override.active

    reconciliation = reconcile_bias(gift_nifty, analyses, override)
    record.divergence_flag = reconciliation.divergence_flag
    record.flat_override_triggered = reconciliation.flat_override_triggered

    paragraph_4_text = resolve_paragraph_4(
        reconciliation.paragraph_4_token,
        bias_label_plain=BIAS_PLAIN_ENGLISH[reconciliation.bias_label],
        top_signal_plain_english=reconciliation.top_signal_plain_english,
    )

    return {
        "record": record,
        "suppressed": False,
        "gift_nifty": gift_nifty,
        "instrument_snapshots": instrument_snapshots,
        "events": events,
        "analyses": analyses,
        "sector_scorecards": sector_scorecards,
        "domestic_override": override,
        "reconciliation": reconciliation,
        "paragraph_4_text": paragraph_4_text,
    }
