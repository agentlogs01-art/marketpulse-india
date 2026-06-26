"""
scheduler/record_daily_close.py

End-of-day companion to run_daily_briefing.py. Fetches the official
Nifty 50 close (post 15:30 IST settlement) and persists it to the
Supabase `market_closes` table via persistence/market_close_repo, so
tomorrow morning's 06:45 IST GIFT Nifty snapshot step has a baseline
without needing a live call during the critical path.

Usage:
    python -m marketpulse.scheduler.record_daily_close

Run this on a schedule shortly after NSE close (15:30 IST) -- see the
second cron entry in .github/workflows/daily_briefing.yml (15:45 IST).
"""

from __future__ import annotations

import sys
from typing import Optional

from marketpulse.persistence.market_close_repo import record_close
from marketpulse.utils.timeutils import now_ist


def fetch_official_nifty_close() -> float:
    """
    Fetch the official Nifty 50 close from Yahoo Finance's free chart
    endpoint (^NSEI), reusing the same free-tier data source already
    used elsewhere in the pipeline (pipeline/market_data.py) to avoid
    introducing a new paid dependency.
    """
    import requests

    resp = requests.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI",
        timeout=10,
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception as e:
        print(f"Yahoo close fetch failed ({e}). Attempting Stooq secondary close...")
        
        # Leverage your existing reliable Stooq framework as a robust backup close!
        try:
            stooq_resp = requests.get("https://stooq.com/q/l/?s=^nsei&f=sd2t2ohlcv&h&e=csv", timeout=10)
            stooq_resp.raise_for_status()
            # CSV Order: Symbol,Date,Time,Open,High,Low,Close,Volume
            line = stooq_resp.text.strip().splitlines()[-1]
            return float(line.split(",")[6])
        except Exception as stooq_err:
            raise RuntimeError(f"Both closing data feeds failed: {stooq_err}")


def main(argv: Optional[list] = None) -> int:
    trade_date = now_ist().date().isoformat()

    try:
        close_price = fetch_official_nifty_close()
    except Exception as exc:
        print(f"Failed to fetch official Nifty 50 close: {exc}", file=sys.stderr)
        return 1

    try:
        record_close(trade_date, close_price, source="Yahoo Finance (^NSEI)")
    except Exception as exc:
        print(f"Failed to persist close to Supabase: {exc}", file=sys.stderr)
        return 2

    print(f"Recorded Nifty 50 close for {trade_date}: {close_price:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
