"""
persistence/run_log_repo.py

Repositories for the `pipeline_runs` and `send_log` tables.

This is the persistence-layer counterpart to utils/qa_logging.py:
qa_logging writes a JSON line to stdout (captured by GitHub Actions /
Railway log aggregation, $0/mo), while this module writes the same
PipelineRunRecord to Supabase so it's queryable later -- e.g. "show me
every day this month the SEBI entity scrubber had to fire" or "how many
times has the flat-override path triggered this quarter." Both are kept;
stdout logging is the zero-dependency fallback, Supabase is the durable
queryable record.
"""

from __future__ import annotations

from typing import Optional

from marketpulse.models.schemas import PipelineRunRecord
from marketpulse.persistence.supabase_client import SupabaseClient, get_client

RUNS_TABLE = "pipeline_runs"
SEND_LOG_TABLE = "send_log"


def record_pipeline_run(
    record: PipelineRunRecord,
    *,
    bias_label: Optional[str] = None,
    gift_nifty_pct_change: Optional[float] = None,
    briefing_html: Optional[str] = None,
    briefing_text: Optional[str] = None,
    client: Optional[SupabaseClient] = None,
) -> dict:
    """
    Persist a PipelineRunRecord. Upserts on run_date_ist so re-running
    the pipeline for the same day (e.g. a manual retry after a partial
    failure) overwrites rather than duplicates -- run_date_ist has a
    UNIQUE constraint in schema.sql for exactly this reason.

    `briefing_html` / `briefing_text` cache the rendered output for that
    day so the authenticated website dashboard (api.handlers
    .get_latest_briefing) can serve it without re-rendering or re-running
    the pipeline on every page view.
    """
    client = client or get_client()
    row = {
        "run_date_ist": record.run_date_ist,
        "domestic_override_active": record.domestic_override_active,
        "divergence_flag": record.divergence_flag,
        "flat_override_triggered": record.flat_override_triggered,
        "jargon_injections": record.jargon_injections,
        "entity_violations": record.entity_violations,
        "suppressed": record.suppressed,
        "suppression_reason": record.suppression_reason,
        "bias_label": bias_label,
        "gift_nifty_pct_change": gift_nifty_pct_change,
    }
    if briefing_html is not None:
        row["briefing_html"] = briefing_html
    if briefing_text is not None:
        row["briefing_text"] = briefing_text
    return client.upsert(RUNS_TABLE, row, on_conflict="run_date_ist")


def record_send_results(
    pipeline_run_id: str,
    sent: list,
    failed: list,
    client: Optional[SupabaseClient] = None,
) -> None:
    """
    Persist per-recipient delivery outcomes for a given run.

    Two accepted shapes, for backward compatibility with the Email-only
    callers (email_system.sender.send_email's result dict) as well as the
    newer multi-channel dispatcher (delivery.dispatcher.flatten_results_for_audit):

      - Plain strings (legacy, email-only): sent=["a@x.com", ...],
        failed=[{"address": "a@x.com", "error": "..."}, ...]
        -> recorded with channel='email'.
      - Channel-tagged dicts (current, any channel): sent=[{"address":
        ..., "channel": "whatsapp"}, ...], failed=[{"address": ...,
        "error": ..., "channel": "telegram"}, ...].
    """
    client = client or get_client()

    for entry in sent:
        if isinstance(entry, dict):
            address, channel = entry["address"], entry.get("channel", "email")
        else:
            address, channel = entry, "email"
        row = {"pipeline_run_id": pipeline_run_id, "channel": channel, "status": "sent"}
        if channel == "email":
            row["recipient_email"] = address
        client.insert(SEND_LOG_TABLE, row, return_row=False)

    for failure in failed:
        channel = failure.get("channel", "email")
        row = {
            "pipeline_run_id": pipeline_run_id,
            "channel": channel,
            "status": "failed",
            "error_message": failure.get("error"),
        }
        if channel == "email":
            row["recipient_email"] = failure["address"]
        client.insert(SEND_LOG_TABLE, row, return_row=False)


def get_run_history(limit: int = 30, client: Optional[SupabaseClient] = None) -> list:
    """Most recent `limit` pipeline runs, newest first -- for a future QA dashboard."""
    client = client or get_client()
    return client.select(
        RUNS_TABLE,
        params={"order": "run_date_ist.desc", "limit": str(limit)},
    )


def get_run_by_date(run_date_iso: str, client: Optional[SupabaseClient] = None) -> Optional[dict]:
    client = client or get_client()
    rows = client.select(RUNS_TABLE, params={"run_date_ist": f"eq.{run_date_iso}"})
    return rows[0] if rows else None


def get_latest_run(client: Optional[SupabaseClient] = None) -> Optional[dict]:
    """
    Returns the most recent pipeline_runs row regardless of date -- this
    is what api.handlers.get_latest_briefing reads to serve "today's
    briefing" (or, if today's run hasn't happened yet/was suppressed,
    whatever the last successful run was) inside the signed-in dashboard.
    """
    client = client or get_client()
    rows = client.select(
        RUNS_TABLE,
        params={"order": "run_date_ist.desc", "limit": "1"},
    )
    return rows[0] if rows else None
