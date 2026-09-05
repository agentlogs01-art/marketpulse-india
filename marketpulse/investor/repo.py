"""Supabase access for investor tables, with in-memory fallbacks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from marketpulse.investor.catalog import FIXED_INCOME, SGB_SERIES, STOCKS
from marketpulse.investor.crypto import decrypt_holdings_blob, encrypt_holdings_blob
from marketpulse.persistence.supabase_client import SupabaseRequestError, get_client


def _client():
    return get_client()


def save_portfolio(subscriber_id: str, source: str, filename: str, holdings: list) -> dict:
    client = _client()
    blob = encrypt_holdings_blob(holdings)
    row = {
        "subscriber_id": subscriber_id,
        "source": source,
        "filename": filename,
        "holdings_ciphertext": blob,
        "parse_status": "parsed",
        "parse_error": None,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    saved = client.insert("portfolios", row)
    portfolio_id = saved.get("id") if saved else None
    for holding in holdings:
        payload = {
            "portfolio_id": portfolio_id,
            "subscriber_id": subscriber_id,
            "symbol": holding.get("symbol"),
            "company_name": holding.get("company_name"),
            "isin": holding.get("isin"),
            "asset_type": holding.get("asset_type") or "equity",
            "sector": holding.get("sector"),
            "quantity": holding.get("quantity") or 0,
            "avg_price": holding.get("avg_price") or 0,
            "current_price": holding.get("current_price") or 0,
            "market_value": holding.get("market_value") or 0,
            "fund_name": holding.get("fund_name"),
            "purchase_date": holding.get("purchase_date"),
        }
        try:
            client.insert("portfolio_holdings", payload)
        except SupabaseRequestError:
            break
    return saved or row


def load_holdings(subscriber_id: str) -> list:
    client = _client()
    try:
        portfolios = client.select(
            "portfolios",
            params={
                "subscriber_id": f"eq.{subscriber_id}",
                "order": "uploaded_at.desc",
                "limit": "1",
            },
        )
    except SupabaseRequestError:
        return []
    if not portfolios:
        return []
    latest = portfolios[0]
    if latest.get("holdings_ciphertext"):
        try:
            return decrypt_holdings_blob(latest["holdings_ciphertext"])
        except Exception:
            pass
    try:
        rows = client.select(
            "portfolio_holdings",
            params={
                "subscriber_id": f"eq.{subscriber_id}",
                "portfolio_id": f"eq.{latest.get('id')}",
            },
        )
        return rows
    except SupabaseRequestError:
        return []


def latest_valuation_row() -> Optional[dict]:
    client = _client()
    try:
        rows = client.select(
            "valuation_snapshots",
            params={"order": "as_of_date.desc", "limit": "1"},
        )
        return rows[0] if rows else None
    except (SupabaseRequestError, Exception):
        return None


def upsert_valuation(snapshot: dict) -> None:
    client = _client()
    row = {k: snapshot[k] for k in (
        "as_of_date", "nifty_pe", "nifty_pb", "dividend_yield", "market_cap_to_gdp",
        "zone", "zone_badge", "nifty50_level", "smallcap250_level", "gsec_10y_yield", "source",
    ) if k in snapshot}
    try:
        client.upsert("valuation_snapshots", row, on_conflict="as_of_date")
    except (SupabaseRequestError, Exception):
        pass


def list_notifications(subscriber_id: str, limit: int = 12) -> list:
    client = _client()
    try:
        return client.select(
            "investor_notifications",
            params={
                "subscriber_id": f"eq.{subscriber_id}",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )
    except (SupabaseRequestError, Exception):
        return []


def count_notifications_since(subscriber_id: str, since_iso: str) -> int:
    rows = list_notifications(subscriber_id, limit=50)
    return sum(1 for r in rows if str(r.get("created_at") or "") >= since_iso)


def insert_notification(subscriber_id: str, kind: str, title: str, body: str) -> Optional[dict]:
    client = _client()
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "subscriber_id": subscriber_id,
        "kind": kind,
        "title": title,
        "body": body,
        "created_at": now,
        "dispatched_at": now,
    }
    try:
        return client.insert("investor_notifications", row)
    except (SupabaseRequestError, Exception):
        return row


def week_window_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()


def stock_search_rows(query: str) -> list:
    from marketpulse.investor.catalog import search_stocks

    catalog_hits = search_stocks(query)
    try:
        client = _client()
        rows = client.select("stock_universe", params={"limit": "80"})
        if rows:
            q = (query or "").strip().lower().replace(".ns", "").replace(".bo", "")
            tokens = [t for t in q.replace(",", " ").split() if t]
            db_hits = []
            for r in rows:
                hay = f"{r.get('symbol','')} {r.get('company_name','')} {r.get('nse_symbol','')} {r.get('bse_code','')}".lower()
                if q and (q in hay or all(t in hay for t in tokens)):
                    db_hits.append(r)
            if db_hits:
                return db_hits[:8]
    except (SupabaseRequestError, Exception):
        pass
    return catalog_hits


def seed_catalog_tables() -> None:
    """Best-effort upsert of static cards so a fresh Supabase project has rows."""
    client = _client()
    for stock in STOCKS:
        try:
            client.upsert("stock_universe", stock, on_conflict="symbol")
        except Exception:
            return
    for item in FIXED_INCOME:
        try:
            client.upsert("fixed_income_instruments", item, on_conflict="id")
        except Exception:
            return
    for item in SGB_SERIES:
        try:
            client.upsert("sgb_series", item, on_conflict="series")
        except Exception:
            return


_WATCHLIST = {}


def _watch_key(subscriber_id: str, symbol: str) -> tuple:
    return (subscriber_id, (symbol or "").upper().strip())


def record_ticker_view(subscriber_id: str, symbol: str, is_favorite: Optional[bool] = None) -> dict:
    symbol = (symbol or "").upper().strip()
    key = _watch_key(subscriber_id, symbol)
    row = dict(_WATCHLIST.get(key) or {
        "subscriber_id": subscriber_id,
        "symbol": symbol,
        "is_favorite": False,
    })
    row["last_viewed_at"] = datetime.now(timezone.utc).isoformat()
    if is_favorite is not None:
        row["is_favorite"] = bool(is_favorite)
    _WATCHLIST[key] = row
    try:
        client = _client()
        client.upsert("ticker_watchlist", row, on_conflict="subscriber_id,symbol")
    except Exception:
        pass
    return row


def list_ticker_watchlist(subscriber_id: str) -> list:
    mem = [row for key, row in _WATCHLIST.items() if key[0] == subscriber_id]
    mem.sort(key=lambda r: r.get("last_viewed_at") or "", reverse=True)
    if mem:
        return mem[:20]
    try:
        client = _client()
        rows = client.select(
            "ticker_watchlist",
            params={"subscriber_id": f"eq.{subscriber_id}", "order": "last_viewed_at.desc", "limit": "20"},
        )
        if rows:
            return rows
    except Exception:
        pass
    return []
