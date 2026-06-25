"""
scheduler/run_daily_briefing.py

Single entry point invoked by a GitHub Actions cron job (PRD Section 3:
GitHub Actions free tier used for scheduling -- $0/mo). The workflow YAML
should trigger this script at 06:00 IST (00:30 UTC); the script itself
sleeps internally until the 06:45 / 06:50 / 07:00 checkpoints so the
whole critical path runs inside one process/log stream.

Usage (from repo root):
    python -m marketpulse.scheduler.run_daily_briefing

Previous-close resolution order:
  1. `--prev-close` CLI flag, if supplied (manual override / test escape
     hatch -- always wins if present).
  2. Supabase `market_closes` table, via persistence/market_close_repo's
     get_latest_close() -- the normal production path. A separate
     end-of-day job (not this script) is responsible for writing that
     day's official Nifty 50 close there shortly after market close.

If neither source resolves, the script exits with an error rather than
guessing -- a wrong baseline would silently corrupt every downstream
bias calculation (FR-02.5), so failing loudly here is the safer choice.

Delivery: fans out to every active subscriber across all three channels
(Email, WhatsApp, Telegram) via delivery/dispatcher.py. A subscriber with
no channels deliverable today (e.g. Telegram chat_id not yet bound) is
simply skipped on that channel -- this is not treated as a failure.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from marketpulse.delivery.dispatcher import dispatch_all_channels, flatten_results_for_audit
from marketpulse.email_system.render import render_subject_and_html
from marketpulse.pipeline.orchestrator import run_full_pipeline
from marketpulse.utils.qa_logging import log_run_record, summarize_record
from marketpulse.utils.timeutils import seconds_until_checkpoint


def wait_until(checkpoint: str) -> None:
    remaining = seconds_until_checkpoint(checkpoint)
    if remaining > 0:
        time.sleep(remaining)


def resolve_prev_close(cli_value: Optional[float]) -> Optional[float]:
    if cli_value is not None:
        return cli_value
    try:
        from marketpulse.persistence.market_close_repo import get_latest_close

        latest = get_latest_close()
        if latest:
            return float(latest["nifty_close"])
    except Exception as exc:
        print(f"Could not reach Supabase for prev-close lookup: {exc}", file=sys.stderr)
    return None


def persist_run_and_send_results(
    output: dict,
    dispatch_results: Optional[dict],
    briefing_html: Optional[str] = None,
    briefing_text: Optional[str] = None,
) -> None:
    """
    Best-effort persistence to Supabase (pipeline_runs + send_log).
    Failures here are logged but never abort the run -- delivery has
    already happened (or the suppression decision already made) by the
    time this is called, so a Supabase outage at this point shouldn't be
    treated as a pipeline failure. stdout QA logging (utils/qa_logging)
    already captured the essential audit trail regardless.

    `briefing_html` / `briefing_text` (when provided) are cached on the
    pipeline_runs row so the website's signed-in dashboard
    (api.handlers.get_latest_briefing) can serve today's briefing without
    re-rendering it.
    """
    try:
        from marketpulse.persistence.run_log_repo import record_pipeline_run, record_send_results

        reconciliation = output.get("reconciliation")
        gift_nifty = output.get("gift_nifty")
        run_row = record_pipeline_run(
            output["record"],
            bias_label=reconciliation.bias_label.value if reconciliation else None,
            gift_nifty_pct_change=gift_nifty.pct_change_vs_prev_close if gift_nifty else None,
            briefing_html=briefing_html,
            briefing_text=briefing_text,
        )
        if dispatch_results and run_row:
            sent, failed = flatten_results_for_audit(dispatch_results)
            record_send_results(run_row["id"], sent, failed)
    except Exception as exc:
        print(f"Supabase audit-log persistence failed (non-fatal): {exc}", file=sys.stderr)


def summarize_dispatch(results: dict) -> str:
    parts = []
    for channel, result in results.items():
        if result is None:
            parts.append(f"{channel}=skipped")
        else:
            parts.append(f"{channel}={len(result['sent'])}/{result['total']}")
    return " | ".join(parts)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MarketPulse India daily briefing pipeline.")
    parser.add_argument(
        "--prev-close",
        type=float,
        default=None,
        help="Previous day's official Nifty 50 close. If omitted, read from Supabase market_closes.",
    )
    parser.add_argument(
        "--skip-wait",
        action="store_true",
        help="Skip the internal sleep-until-checkpoint waits (useful for manual/test runs)",
    )
    args = parser.parse_args(argv)

    if not args.skip_wait:
        wait_until("snapshot")  # blocks until 06:45 IST

    prev_close = resolve_prev_close(args.prev_close)
    if prev_close is None:
        print(
            "No previous Nifty close available (no --prev-close flag and "
            "Supabase market_closes has no rows). Aborting rather than guessing.",
            file=sys.stderr,
        )
        return 3

    output = run_full_pipeline(prev_nifty_close=prev_close)
    record = output["record"]
    log_run_record(record)
    print(summarize_record(record), file=sys.stderr)

    if output["suppressed"]:
        persist_run_and_send_results(output, dispatch_results=None)
        print("Run suppressed -- no delivery attempted. See QA log above.", file=sys.stderr)
        return 1

    if not args.skip_wait:
        wait_until("send")  # blocks until 07:00 IST

    subject, html = render_subject_and_html(output)
    dispatch_results = dispatch_all_channels(output, subject, html)

    from marketpulse.delivery.text_render import render_plain_text

    briefing_text = render_plain_text(output)
    persist_run_and_send_results(output, dispatch_results, briefing_html=html, briefing_text=briefing_text)
    print(summarize_dispatch(dispatch_results), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
