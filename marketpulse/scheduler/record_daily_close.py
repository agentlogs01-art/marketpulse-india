"""
scheduler/record_daily_close.py

End-of-day companion to run_daily_briefing.py. Fetches the official
Nifty 50 close (post 15:30 IST settlement) and persists it to the
Supabase `market_closes` table via persistence/market_close_repo, so
tomorrow morning's 06:45 IST GIFT Nifty snapshot step has a baseline
without needing a live call during the critical path.

Usage:
    python -m marketpulse.scheduler.record_daily_close
"""

from __future__ import annotations

import sys
from typing import Optional

from marketpulse.persistence.market_close_repo import record_close
from marketpulse.pipeline.market_data import fetch_quote
from marketpulse.utils.timeutils import now_ist


def get_official_nifty_close() -> float:
    """Yahoo (browser headers) then Stooq — same path as the morning snapshot."""
    quote = fetch_quote("^NSEI", "^nsei")
    close_price = float(quote["price"])
    print(f"[✓] Nifty 50 close from {quote['source']}: {close_price}", file=sys.stderr)
    return close_price


def main(argv: Optional[list] = None) -> int:
    trade_date = now_ist().date().isoformat()

    try:
        close_price = get_official_nifty_close()
    except Exception as exc:
        print(f"Failed to fetch official Nifty 50 close: {exc}", file=sys.stderr)
        return 1

    try:
        record_close(trade_date, close_price, source="Yahoo Finance / Stooq (^NSEI)")
    except Exception as exc:
        print(f"Failed to persist close to Supabase: {exc}", file=sys.stderr)
        return 2

    print(f"Recorded Nifty 50 close for {trade_date}: {close_price:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
