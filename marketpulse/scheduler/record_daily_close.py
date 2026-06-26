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

import requests
import sys

def get_official_nifty_close() -> float:
    """
    Fetches the final official closing price of Nifty 50.
    Tries Yahoo Finance with advanced headers first, but falls back instantly
    to Stooq if Yahoo returns a 429 or drops connection on GitHub Actions.
    """
    # 1. Primary Source: Yahoo Finance with full header spoofing
    yahoo_url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI"
    yahoo_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://finance.yahoo.com",
        "Referer": "https://finance.yahoo.com/"
    }

    try:
        print("[+] Attempting to fetch Nifty 50 close from Yahoo Finance...")
        resp = requests.get(yahoo_url, headers=yahoo_headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        close_price = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
        print(f"[✓] Successfully fetched from Yahoo: {close_price}")
        return close_price
    except Exception as e:
        print(f"[!] Yahoo Finance failed (likely data-center 429 rate limit): {e}")
        print("[+] Activating secondary fallback source: Stooq...")

    # 2. Secondary Fallback Source: Stooq (extremely reliable on CI/CD environments)
    try:
        stooq_url = "https://stooq.com/q/l/?s=^nsei&f=sd2t2ohlcv&h&e=csv"
        resp = requests.get(stooq_url, timeout=10)
        resp.raise_for_status()
        
        # CSV layout layout: Symbol,Date,Time,Open,High,Low,Close,Volume
        lines = resp.text.strip().splitlines()
        if len(lines) < 2:
            raise ValueError("Stooq returned insufficient historical or structural records.")
            
        last_line = lines[-1].split(",")
        close_price = float(last_line[6])  # Index 6 corresponds directly to Close
        print(f"[✓] Successfully retrieved Nifty 50 close from Stooq Fallback: {close_price}")
        return close_price
    except Exception as stooq_err:
        print(f"[-] Critical Error: Both Yahoo Finance and Stooq fallback providers failed: {stooq_err}")
        sys.exit(1) # Gracefully kill execution only if both systems fail completely

def main(argv: Optional[list] = None) -> int:
    trade_date = now_ist().date().isoformat()

    try:
        #close_price = fetch_official_nifty_close()
        close_price = get_official_nifty_close()
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
