"""
pipeline/market_data.py

FR-01.1 — Market Instrument Snapshot ingestion, including the
GIFT Nifty pipeline with its strict IST timeline:

    06:00 IST  pre-render (static content, templates)
    06:45 IST  GIFT Nifty snapshot capture
    06:50 IST  assembly (bias reconciliation + email render)
    07:00 IST  send

This module implements the snapshot capture step with the three-tier
fallback chain called out in the schema (GiftNiftySnapshot.is_fallback /
is_estimated):

    1. Primary:  nseifsc.com (NSE IFSC GIFT Nifty official feed)
    2. Fallback: Yahoo Finance GIFTY=F ticker
    3. Last resort: Stooq ^NSEI proxy (estimated, flagged to the reader)

All three are free data sources, consistent with the <$100/mo infra
budget (Section 3) — no paid market data vendor in the MVP.
"""

from __future__ import annotations

from datetime import datetime, timezone

from marketpulse.models.schemas import GiftNiftySnapshot, InstrumentSnapshot

DATA_DELAYED_THRESHOLD_HOURS = 6  # FR-01.1: flag "Data Delayed" beyond this age


# ---------------------------------------------------------------------------
# GIFT Nifty — three-tier fallback chain
# ---------------------------------------------------------------------------

def _fetch_gift_nifty_primary() -> dict:
    """Primary source: NSE IFSC official GIFT Nifty feed."""
    import requests

    resp = requests.get("https://www.nseifsc.com/api/quote-derivative/NIFTY", timeout=8)
    resp.raise_for_status()
    return resp.json()


def _fetch_gift_nifty_yahoo_fallback() -> dict:
    """Fallback source: Yahoo Finance GIFTY=F futures ticker."""
    import requests

    resp = requests.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/GIFTY=F",
        timeout=8,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_stooq_nsei_estimate() -> dict:
    """Last-resort estimated proxy: Stooq ^NSEI (regular Nifty 50, not a
    true GIFT Nifty futures read — flagged is_estimated=True downstream so
    the email can show an "Estimated" disclaimer per FR-01.1)."""
    import requests

    resp = requests.get("https://stooq.com/q/l/?s=^nsei&f=sd2t2ohlcv&h&e=csv", timeout=8)
    resp.raise_for_status()
    return {"csv": resp.text}


def fetch_gift_nifty_snapshot(prev_nifty_close: float) -> GiftNiftySnapshot:
    """
    Capture the 06:45 IST GIFT Nifty snapshot, walking the fallback chain.
    `prev_nifty_close` must be supplied by the caller (previous day's
    Nifty 50 official close, fetched separately at pre-render/06:00 IST
    since it doesn't change intraday).
    """
    captured_at = datetime.now(timezone.utc).isoformat()

    try:
        data = _fetch_gift_nifty_primary()
        ltp = float(data["data"]["lastPrice"])
        pct_change = ((ltp - prev_nifty_close) / prev_nifty_close) * 100
        return GiftNiftySnapshot(
            last_traded_price=ltp,
            pct_change_vs_prev_close=pct_change,
            prev_nifty_close=prev_nifty_close,
            captured_at_ist=captured_at,
            source="nseifsc.com",
        )
    except Exception:
        pass

    try:
        data = _fetch_gift_nifty_yahoo_fallback()
        ltp = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
        pct_change = ((ltp - prev_nifty_close) / prev_nifty_close) * 100
        return GiftNiftySnapshot(
            last_traded_price=ltp,
            pct_change_vs_prev_close=pct_change,
            prev_nifty_close=prev_nifty_close,
            captured_at_ist=captured_at,
            source="Yahoo Finance (GIFTY=F)",
            is_fallback=True,
        )
    except Exception:
        pass

    try:
        data = _fetch_stooq_nsei_estimate()
        # CSV format: Symbol,Date,Time,Open,High,Low,Close,Volume
        line = data["csv"].strip().splitlines()[-1]
        close_price = float(line.split(",")[6])
        pct_change = ((close_price - prev_nifty_close) / prev_nifty_close) * 100
        return GiftNiftySnapshot(
            last_traded_price=close_price,
            pct_change_vs_prev_close=pct_change,
            prev_nifty_close=prev_nifty_close,
            captured_at_ist=captured_at,
            source="Stooq ^NSEI (estimated proxy)",
            is_fallback=True,
            is_estimated=True,
        )
    except Exception:
        pass

    # All three sources failed — return a FLAT estimate so the deterministic
    # Branch A (flat override) path in bias_engine kicks in safely rather
    # than crashing the 06:50 assembly step.
    return GiftNiftySnapshot(
        last_traded_price=prev_nifty_close,
        pct_change_vs_prev_close=0.0,
        prev_nifty_close=prev_nifty_close,
        captured_at_ist=captured_at,
        source="unavailable (defaulted to flat)",
        is_fallback=True,
        is_estimated=True,
    )


# ---------------------------------------------------------------------------
# Other market instruments — Section 2 Market Snapshot table (FR-01.1)
# ---------------------------------------------------------------------------

INSTRUMENT_SOURCES = [
    {"name": "Dow Jones (US)", "unit": "index pts", "yahoo_symbol": "^DJI"},
    {"name": "Nasdaq (US)", "unit": "index pts", "yahoo_symbol": "^IXIC"},
    {"name": "Nikkei 225 (Japan)", "unit": "index pts", "yahoo_symbol": "^N225"},
    {"name": "Hang Seng (Hong Kong)", "unit": "index pts", "yahoo_symbol": "^HSI"},
    {"name": "Brent Crude Oil", "unit": "USD/barrel", "yahoo_symbol": "BZ=F"},
    {"name": "Gold", "unit": "USD/oz", "yahoo_symbol": "GC=F"},
    {"name": "USD/INR", "unit": "INR", "yahoo_symbol": "INR=X"},
    {"name": "US 10-Year Treasury Yield", "unit": "%", "yahoo_symbol": "^TNX"},
    {"name": "Dollar Index (DXY)", "unit": "index pts", "yahoo_symbol": "DX-Y.NYB"},
]


def fetch_instrument_snapshot(spec: dict) -> InstrumentSnapshot:
    """Fetch a single instrument from Yahoo Finance's free chart endpoint."""
    import requests

    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{spec['yahoo_symbol']}",
            timeout=8,
        )
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]
        price = float(meta["regularMarketPrice"])
        prev_close = float(meta["previousClose"])
        pct_change = ((price - prev_close) / prev_close) * 100 if prev_close else 0.0
        return InstrumentSnapshot(
            name=spec["name"],
            value=price,
            pct_change=pct_change,
            unit=spec["unit"],
            fetched_at_utc=fetched_at,
            source="Yahoo Finance",
        )
    except Exception:
        return InstrumentSnapshot(
            name=spec["name"],
            value=0.0,
            pct_change=0.0,
            unit=spec["unit"],
            fetched_at_utc=fetched_at,
            source="unavailable",
            is_delayed=True,
        )


def fetch_all_instrument_snapshots() -> list[InstrumentSnapshot]:
    return [fetch_instrument_snapshot(spec) for spec in INSTRUMENT_SOURCES]


def flag_stale_snapshots(snapshots: list[InstrumentSnapshot]) -> list[InstrumentSnapshot]:
    """FR-01.1: mark any snapshot older than the staleness threshold as
    delayed so the email template can render a "Data Delayed" badge."""
    now = datetime.now(timezone.utc)
    for snap in snapshots:
        try:
            fetched = datetime.fromisoformat(snap.fetched_at_utc.replace("Z", "+00:00"))
        except ValueError:
            continue
        age_hours = (now - fetched).total_seconds() / 3600
        if age_hours > DATA_DELAYED_THRESHOLD_HOURS:
            snap.is_delayed = True
    return snapshots
