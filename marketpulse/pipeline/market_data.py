"""
pipeline/market_data.py

FR-01.1 — Market Instrument Snapshot ingestion, including the
GIFT Nifty pipeline with its strict IST timeline:

    06:00 IST  pre-render (static content, templates)
    06:45 IST  GIFT Nifty snapshot capture
    06:50 IST  assembly (bias reconciliation + email render)
    07:00 IST  send

Yahoo Finance's chart API rejects bare requests from GitHub Actions
datacenters (401/429, empty result). Every quote therefore walks:

    1. Yahoo query2 then query1, with a browser User-Agent
    2. Stooq CSV (free, CI-friendly)

Returning 0.00 / 0% is a last resort only after both sources fail —
that is the value users were seeing when Yahoo was called with no headers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote
import sys

from marketpulse.models.schemas import GiftNiftySnapshot, InstrumentSnapshot

DATA_DELAYED_THRESHOLD_HOURS = 6  # FR-01.1: flag "Data Delayed" beyond this age

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://finance.yahoo.com",
    "Referer": "https://finance.yahoo.com/",
}


# ---------------------------------------------------------------------------
# Shared quote helpers
# ---------------------------------------------------------------------------

def _yahoo_chart_quote(symbol: str) -> dict:
    """Return {price, previous_close} from Yahoo chart meta / daily bars."""
    import requests

    encoded = quote(symbol, safe="")
    last_error: Optional[Exception] = None
    for host in ("query2", "query1"):
        url = (
            f"https://{host}.finance.yahoo.com/v8/finance/chart/{encoded}"
            "?interval=1d&range=5d"
        )
        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
            resp.raise_for_status()
            result = resp.json()["chart"]["result"][0]
            meta = result["meta"]
            price = meta.get("regularMarketPrice")
            prev_close = (
                meta.get("chartPreviousClose")
                or meta.get("previousClose")
            )
            if price is None:
                closes = (result.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
                price = next((c for c in reversed(closes) if c is not None), None)
            if prev_close is None:
                closes = (result.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
                numbered = [c for c in closes if c is not None]
                if len(numbered) >= 2:
                    prev_close = numbered[-2]
                elif numbered:
                    prev_close = numbered[-1]
            if price is None:
                raise ValueError(f"Yahoo chart for {symbol} had no last price")
            if prev_close in (None, 0):
                prev_close = price
            return {
                "price": float(price),
                "previous_close": float(prev_close),
                "source": f"Yahoo Finance ({symbol})",
            }
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"Yahoo chart failed for {symbol}: {last_error}")


def parse_stooq_csv(csv_text: str) -> dict:
    """Parse Stooq `sd2t2ohlcv` CSV. Last non-N/A data row wins."""
    lines = [ln.strip() for ln in csv_text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError("Stooq CSV had no data rows")
    for line in reversed(lines[1:]):
        parts = line.split(",")
        if len(parts) < 7:
            continue
        close_raw = parts[6].strip()
        if not close_raw or close_raw.upper() == "N/A":
            continue
        close_price = float(close_raw)
        open_raw = parts[3].strip()
        prev = float(open_raw) if open_raw and open_raw.upper() != "N/A" else close_price
        return {"price": close_price, "previous_close": prev, "source": f"Stooq ({parts[0]})"}
    raise ValueError("Stooq CSV had only N/A rows")


def _stooq_quote(symbol: str) -> dict:
    import requests

    hist_url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    try:
        resp = requests.get(hist_url, headers=BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
        lines = [ln.strip() for ln in resp.text.strip().splitlines() if ln.strip()]
        rows = lines[1:] if lines and lines[0].lower().startswith("date") else lines
        closes = []
        for row in rows:
            parts = row.split(",")
            if len(parts) < 5:
                continue
            close_raw = parts[4].strip()
            if close_raw and close_raw.upper() != "N/A":
                closes.append(float(close_raw))
        if len(closes) >= 2:
            return {
                "price": closes[-1],
                "previous_close": closes[-2],
                "source": f"Stooq ({symbol})",
            }
        if len(closes) == 1:
            return {
                "price": closes[-1],
                "previous_close": closes[-1],
                "source": f"Stooq ({symbol})",
            }
    except Exception as exc:
        print(f"[market_data] Stooq daily history failed for {symbol}: {exc}", file=sys.stderr)

    url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
    resp.raise_for_status()
    quote = parse_stooq_csv(resp.text)
    quote["source"] = f"Stooq ({symbol})"
    return quote


def fetch_quote(yahoo_symbol: str, stooq_symbol: Optional[str] = None) -> dict:
    """Price + previous close. Yahoo first (with headers), Stooq second."""
    try:
        return _yahoo_chart_quote(yahoo_symbol)
    except Exception as yahoo_err:
        print(f"[market_data] Yahoo failed for {yahoo_symbol}: {yahoo_err}", file=sys.stderr)
    if stooq_symbol:
        try:
            return _stooq_quote(stooq_symbol)
        except Exception as stooq_err:
            print(f"[market_data] Stooq failed for {stooq_symbol}: {stooq_err}", file=sys.stderr)
    raise RuntimeError(f"No quote available for {yahoo_symbol}")


# ---------------------------------------------------------------------------
# GIFT Nifty — three-tier fallback chain
# ---------------------------------------------------------------------------

def _fetch_gift_nifty_primary() -> dict:
    """Primary source: NSE IFSC official GIFT Nifty feed."""
    import requests

    headers = {
        **BROWSER_HEADERS,
        "Referer": "https://www.nseifsc.com/",
        "Origin": "https://www.nseifsc.com",
    }
    resp = requests.get(
        "https://www.nseifsc.com/api/quote-derivative/NIFTY",
        headers=headers,
        timeout=8,
    )
    resp.raise_for_status()
    data = resp.json()
    payload = data.get("data") or data
    ltp = payload.get("lastPrice") or payload.get("ltp") or payload.get("lastTradedPrice")
    if ltp is None:
        raise ValueError(f"NSE IFSC payload missing lastPrice: {list(payload)[:12]}")
    return {"price": float(ltp), "source": "nseifsc.com"}


def fetch_gift_nifty_snapshot(prev_nifty_close: float) -> GiftNiftySnapshot:
    """
    Capture the 06:45 IST GIFT Nifty snapshot, walking the fallback chain.
    `prev_nifty_close` must be supplied by the caller (previous day's
    Nifty 50 official close).
    """
    captured_at = datetime.now(timezone.utc).isoformat()
    if not prev_nifty_close:
        print("[market_data] prev_nifty_close is 0/empty; pct change will be 0", file=sys.stderr)

    try:
        data = _fetch_gift_nifty_primary()
        ltp = data["price"]
        pct_change = ((ltp - prev_nifty_close) / prev_nifty_close) * 100 if prev_nifty_close else 0.0
        return GiftNiftySnapshot(
            last_traded_price=ltp,
            pct_change_vs_prev_close=pct_change,
            prev_nifty_close=prev_nifty_close,
            captured_at_ist=captured_at,
            source=data["source"],
        )
    except Exception as exc:
        print(f"[market_data] NSE IFSC GIFT Nifty failed: {exc}", file=sys.stderr)

    for yahoo_symbol, estimated in (("GIFTY=F", False), ("^NSEI", True)):
        try:
            data = _yahoo_chart_quote(yahoo_symbol)
            ltp = data["price"]
            pct_change = ((ltp - prev_nifty_close) / prev_nifty_close) * 100 if prev_nifty_close else 0.0
            return GiftNiftySnapshot(
                last_traded_price=ltp,
                pct_change_vs_prev_close=pct_change,
                prev_nifty_close=prev_nifty_close,
                captured_at_ist=captured_at,
                source=data["source"],
                is_fallback=True,
                is_estimated=estimated,
            )
        except Exception as exc:
            print(f"[market_data] Yahoo {yahoo_symbol} failed: {exc}", file=sys.stderr)

    try:
        data = _stooq_quote("^nsei")
        close_price = data["price"]
        pct_change = (
            ((close_price - prev_nifty_close) / prev_nifty_close) * 100
            if prev_nifty_close
            else 0.0
        )
        return GiftNiftySnapshot(
            last_traded_price=close_price,
            pct_change_vs_prev_close=pct_change,
            prev_nifty_close=prev_nifty_close,
            captured_at_ist=captured_at,
            source="Stooq ^NSEI (estimated proxy)",
            is_fallback=True,
            is_estimated=True,
        )
    except Exception as exc:
        print(f"[market_data] Stooq ^nsei failed: {exc}", file=sys.stderr)

    # All sources failed — Branch A (flat override) rather than crashing assembly.
    print("[market_data] All GIFT Nifty sources failed; defaulting to flat", file=sys.stderr)
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
    {"name": "Dow Jones (US)", "unit": "index pts", "yahoo_symbol": "^DJI", "stooq_symbol": "^dji"},
    {"name": "Nasdaq (US)", "unit": "index pts", "yahoo_symbol": "^IXIC", "stooq_symbol": "^ndq"},
    {"name": "Nikkei 225 (Japan)", "unit": "index pts", "yahoo_symbol": "^N225", "stooq_symbol": "^nkx"},
    {"name": "Hang Seng (Hong Kong)", "unit": "index pts", "yahoo_symbol": "^HSI", "stooq_symbol": "^hsi"},
    {"name": "Brent Crude Oil", "unit": "USD/barrel", "yahoo_symbol": "BZ=F", "stooq_symbol": "brn.f"},
    {"name": "Gold", "unit": "USD/oz", "yahoo_symbol": "GC=F", "stooq_symbol": "gc.f"},
    {"name": "USD/INR", "unit": "INR", "yahoo_symbol": "INR=X", "stooq_symbol": "usdind"},
    {"name": "US 10-Year Treasury Yield", "unit": "%", "yahoo_symbol": "^TNX", "stooq_symbol": "10usy.b"},
    {"name": "Dollar Index (DXY)", "unit": "index pts", "yahoo_symbol": "DX-Y.NYB", "stooq_symbol": "dx.f"},
]


def fetch_instrument_snapshot(spec: dict) -> InstrumentSnapshot:
    """Fetch a single instrument from Yahoo, then Stooq. Never silently zero a live quote."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        quote = fetch_quote(spec["yahoo_symbol"], spec.get("stooq_symbol"))
        price = quote["price"]
        prev_close = quote["previous_close"]
        pct_change = ((price - prev_close) / prev_close) * 100 if prev_close else 0.0
        return InstrumentSnapshot(
            name=spec["name"],
            value=price,
            pct_change=pct_change,
            unit=spec["unit"],
            fetched_at_utc=fetched_at,
            source=quote["source"],
            is_delayed="Stooq" in quote["source"],
        )
    except Exception as exc:
        print(f"[market_data] {spec['name']} unavailable: {exc}", file=sys.stderr)
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
    snapshots = [fetch_instrument_snapshot(spec) for spec in INSTRUMENT_SOURCES]
    live = sum(1 for s in snapshots if s.value)
    print(
        f"[market_data] instrument snapshots: {live}/{len(snapshots)} with a non-zero price",
        file=sys.stderr,
    )
    return snapshots


def format_market_context_for_llm(
    gift_nifty: GiftNiftySnapshot,
    snapshots: list[InstrumentSnapshot],
) -> str:
    """Compact overnight tape the LLM can condition on without inventing prices."""
    lines = [
        "Overnight market snapshot (factual tape — do not invent or override these numbers):",
        (
            f"GIFT/Nifty preview: {gift_nifty.last_traded_price:.2f} "
            f"({gift_nifty.pct_change_vs_prev_close:+.2f}% vs previous Nifty close "
            f"{gift_nifty.prev_nifty_close:.2f}); source={gift_nifty.source}"
        ),
    ]
    for snap in snapshots:
        if not snap.value:
            continue
        lines.append(
            f"{snap.name}: {snap.value:.2f} {snap.unit} ({snap.pct_change:+.2f}%)"
        )
    return "\n".join(lines)


def flag_stale_snapshots(snapshots: list[InstrumentSnapshot]) -> list[InstrumentSnapshot]:
    """FR-01.1: mark any snapshot older than the staleness threshold as delayed."""
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
