"""
Additive investor API handlers.

New routes (wired in api/app.py) — existing /api/login, /api/me, etc. are untouched:
  POST /api/v1/portfolio/upload
  GET  /api/v1/portfolio/analysis
  GET  /api/v1/stocks/search?q=
  GET  /api/v1/stocks/<symbol>
  GET  /api/v1/investor/valuation-zone
  GET  /api/v1/fixed-income/secured
  GET  /api/v1/investor/notifications
"""

from __future__ import annotations

from marketpulse.api.handlers import AuthError, ValidationError, _require_session
from marketpulse.investor import repo
from marketpulse.investor.cas_parser import parse_holdings_payload
from marketpulse.investor.catalog import (
    FIXED_INCOME,
    SGB_SERIES,
    filings_for,
    get_stock,
    search_stocks,
)
from marketpulse.investor.diagnostics import analyze_portfolio
from marketpulse.investor.notifications import maybe_dispatch_from_analysis, watchlist_filing_alerts
from marketpulse.investor.valuation import build_valuation_snapshot


def _valuation_payload() -> dict:
    stored = repo.latest_valuation_row()
    if stored:
        snap = build_valuation_snapshot(stored)
        snap["as_of_date"] = stored.get("as_of_date") or snap["as_of_date"]
        snap["source"] = stored.get("source") or snap["source"]
        return snap
    snap = build_valuation_snapshot()
    repo.upsert_valuation(snap)
    return snap


def upload_portfolio(session_token: str, raw: bytes = b"", filename: str = "", broker_token: str = "") -> dict:
    subscriber = _require_session(session_token)
    try:
        parsed = parse_holdings_payload(raw or b"", filename=filename, broker_token=broker_token)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    saved = repo.save_portfolio(
        subscriber.id,
        parsed["source"],
        parsed.get("filename") or filename,
        parsed["holdings"],
    )
    return {
        "ok": True,
        "source": parsed["source"],
        "filename": parsed.get("filename") or filename,
        "holdings_count": len(parsed["holdings"]),
        "portfolio_id": saved.get("id"),
    }


def get_portfolio_analysis(session_token: str) -> dict:
    subscriber = _require_session(session_token)
    holdings = repo.load_holdings(subscriber.id)
    valuation = _valuation_payload()
    analysis = analyze_portfolio(holdings, valuation_zone=valuation["zone"])
    maybe_dispatch_from_analysis(subscriber.id, analysis, valuation)
    watchlist_filing_alerts(
        subscriber.id,
        holdings,
        {h.get("symbol"): filings_for(h.get("symbol") or "") for h in holdings},
    )
    return {
        "ok": True,
        "valuation_zone": valuation["zone"],
        "analysis": analysis,
        "empty": not holdings,
    }


def search_stock_symbols(session_token: str, query: str) -> dict:
    _require_session(session_token)
    rows = repo.stock_search_rows(query) or search_stocks(query)
    results = [
        {
            "symbol": r.get("symbol"),
            "nse_symbol": r.get("nse_symbol"),
            "bse_code": r.get("bse_code"),
            "company_name": r.get("company_name"),
            "sector": r.get("sector"),
            "market_cap_category": r.get("market_cap_category"),
        }
        for r in rows
    ]
    return {"ok": True, "results": results}


def get_stock_detail(session_token: str, symbol: str) -> dict:
    _require_session(session_token)
    row = get_stock(symbol)
    if row is None:
        hits = search_stocks(symbol, limit=1)
        row = hits[0] if hits else None
    if row is None:
        raise ValidationError("No matching NSE/BSE symbol in the long-term universe.")
    detail = dict(row)
    try:
        from marketpulse.pipeline.market_data import fetch_quote

        quote = fetch_quote(row["yahoo_symbol"])
        if quote.get("price"):
            detail["current_price"] = quote["price"]
            detail["quote_source"] = quote.get("source")
    except Exception:
        detail["quote_source"] = "catalog"
    detail["filings"] = filings_for(symbol)
    detail["valuation_vs_median"] = None
    if detail.get("pe") and detail.get("pe_5yr_median"):
        detail["valuation_vs_median"] = round(float(detail["pe"]) - float(detail["pe_5yr_median"]), 2)
    return {"ok": True, "stock": detail}


def get_valuation_zone(session_token: str) -> dict:
    _require_session(session_token)
    snap = _valuation_payload()
    return {"ok": True, **snap}


def get_secured_fixed_income(session_token: str) -> dict:
    _require_session(session_token)
    discounted = [s for s in SGB_SERIES if (s.get("discount_pct") or 0) > 0]
    discounted.sort(key=lambda s: -float(s["discount_pct"]))
    return {
        "ok": True,
        "instruments": FIXED_INCOME,
        "sgb_series": SGB_SERIES,
        "sgb_discount_highlight": discounted[0] if discounted else None,
    }


def get_investor_notifications(session_token: str) -> dict:
    subscriber = _require_session(session_token)
    return {"ok": True, "notifications": repo.list_notifications(subscriber.id)}
