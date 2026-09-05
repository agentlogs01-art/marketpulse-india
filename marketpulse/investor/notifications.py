"""Cap weekly investor alerts at 2–3 high-value items."""

from __future__ import annotations

from marketpulse.investor import repo

MAX_ALERTS_PER_WEEK = 3


def maybe_dispatch_from_analysis(subscriber_id: str, analysis: dict, valuation: dict) -> list:
    existing = repo.list_notifications(subscriber_id)
    if repo.count_notifications_since(subscriber_id, repo.week_window_iso()) >= MAX_ALERTS_PER_WEEK:
        return existing[:MAX_ALERTS_PER_WEEK]

    planned = []
    drift = analysis.get("drift") or {}
    if drift.get("needs_rebalance"):
        planned.append(
            (
                "rebalance",
                "Portfolio drift above 5%",
                f"Equity is {drift.get('equity_pct')}% versus a {drift.get('model_equity_pct')}% model. Rebalance toward secured debt or index equity — not toward trading.",
            )
        )
    if analysis.get("concentration_warnings"):
        warn = analysis["concentration_warnings"][0]
        planned.append(("concentration", "Concentration check", warn["message"]))
    if (analysis.get("overlap") or {}).get("overlap_pct", 0) >= 8:
        planned.append(("overlap", "Fund overlap", analysis["overlap"]["message"]))
    quality = analysis.get("quality_flags") or []
    if quality:
        planned.append(("quality", "Quality / leverage flag", quality[0]["message"]))
    zone = (valuation or {}).get("zone")
    if zone == "overvalued":
        planned.append(
            (
                "valuation",
                "Market valuation zone",
                valuation.get("zone_badge") or "Markets look expensive versus history — favour SIPs into secured debt.",
            )
        )

    created_kinds = {n.get("kind") for n in existing}
    slots = MAX_ALERTS_PER_WEEK - repo.count_notifications_since(subscriber_id, repo.week_window_iso())
    for kind, title, body in planned:
        if slots <= 0:
            break
        if kind in created_kinds:
            continue
        repo.insert_notification(subscriber_id, kind, title, body)
        created_kinds.add(kind)
        slots -= 1
    return repo.list_notifications(subscriber_id)


def watchlist_filing_alerts(subscriber_id: str, holdings: list, filings_by_symbol: dict) -> None:
    if repo.count_notifications_since(subscriber_id, repo.week_window_iso()) >= MAX_ALERTS_PER_WEEK:
        return
    for h in holdings:
        symbol = (h.get("symbol") or "").upper()
        notes = filings_by_symbol.get(symbol) or []
        if not notes:
            continue
        latest = notes[0]
        repo.insert_notification(
            subscriber_id,
            "filing",
            f"{symbol} exchange update",
            f"{latest.get('headline')} — {latest.get('summary_3_5yr')}",
        )
        break
