"""
persistence/market_close_repo.py

Repository for the `market_closes` table.

Why this table exists: the GIFT Nifty snapshot step (FR-01.1, see
pipeline/market_data.fetch_gift_nifty_snapshot) needs the PREVIOUS
trading day's official Nifty 50 close as a baseline to compute
% change. That close is fixed by ~15:30 IST and doesn't change again,
so fetching it live at 06:45 IST the next morning is unnecessary
network risk during the critical path -- instead, a separate end-of-day
job (run any time after market close, e.g. 16:00 IST) persists it here,
and the morning pipeline just reads it back.

This directly replaces the `--prev-close` CLI argument in
scheduler/run_daily_briefing.py with a real lookup, while keeping that
flag as a manual override/test escape hatch.
"""

from __future__ import annotations

from typing import Optional

from marketpulse.persistence.supabase_client import SupabaseClient, get_client

TABLE = "market_closes"


def record_close(trade_date_iso: str, nifty_close: float, source: str = "NSE official",
                  client: Optional[SupabaseClient] = None) -> dict:
    """
    Upsert the official close for a given trade date. Idempotent by
    design (on_conflict=trade_date) so re-running the EOD job twice for
    the same day (e.g. a retry after a transient failure) just overwrites
    with the same value instead of erroring on a duplicate key.
    """
    client = client or get_client()
    return client.upsert(
        TABLE,
        {"trade_date": trade_date_iso, "nifty_close": nifty_close, "source": source},
        on_conflict="trade_date",
    )


def get_close(trade_date_iso: str, client: Optional[SupabaseClient] = None) -> Optional[float]:
    client = client or get_client()
    rows = client.select(
        TABLE,
        params={"trade_date": f"eq.{trade_date_iso}", "select": "nifty_close"},
    )
    return float(rows[0]["nifty_close"]) if rows else None


def get_latest_close(client: Optional[SupabaseClient] = None) -> Optional[dict]:
    """
    Returns the most recently recorded close (trade_date + nifty_close),
    used by the morning pipeline when "yesterday" needs to resolve
    correctly across weekends/holidays without the caller having to know
    the NSE trading calendar -- it just asks for "whatever the last
    recorded close was."
    """
    client = client or get_client()
    rows = client.select(
        TABLE,
        params={
            "select": "trade_date,nifty_close,source",
            "order": "trade_date.desc",
            "limit": "1",
        },
    )
    return rows[0] if rows else None
