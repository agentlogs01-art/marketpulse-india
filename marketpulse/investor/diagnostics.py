"""Portfolio health, concentration, overlap, quality, and rebalancing logic."""

from __future__ import annotations

from datetime import date
from typing import Optional

from marketpulse.investor.catalog import FUND_UNDERLYINGS, STOCK_BY_SYMBOL, scheme_key_from_name


STOCK_CONCENTRATION_PCT = 10.0
SECTOR_CONCENTRATION_PCT = 30.0
ROCE_FLOOR = 10.0
DEBT_EQUITY_CEILING = 1.5
PLEDGE_CEILING = 15.0
DRIFT_PCT = 5.0
BANK_NBFC_SECTORS = {"banking", "financials", "nbfc"}
LTCG_HOLDING_DAYS = 365


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _holding_date(raw) -> Optional[date]:
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    text = str(raw)[:10]
    try:
        y, m, d = text.split("-")
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def classify_sleeve(asset_type: str) -> str:
    t = (asset_type or "equity").lower()
    if t in {"debt", "gold"}:
        return "debt"
    return "equity"


def analyze_portfolio(holdings: list, valuation_zone: str = "fair", as_of: Optional[date] = None) -> dict:
    as_of = as_of or date.today()
    rows = [h for h in holdings if _num(h.get("market_value")) > 0]
    total = sum(_num(h.get("market_value")) for h in rows) or 0.0

    sector_map: dict[str, float] = {}
    sleeve_map = {"equity": 0.0, "debt": 0.0}
    for h in rows:
        sector = h.get("sector") or "Unclassified"
        sector_map[sector] = sector_map.get(sector, 0.0) + _num(h["market_value"])
        sleeve = classify_sleeve(h.get("asset_type"))
        sleeve_map[sleeve] += _num(h["market_value"])

    equity_pct = (sleeve_map["equity"] / total * 100) if total else 0.0
    debt_pct = (sleeve_map["debt"] / total * 100) if total else 0.0

    concentration = []
    for h in rows:
        pct = _num(h["market_value"]) / total * 100 if total else 0.0
        if (h.get("asset_type") or "equity").lower() == "equity" and pct > STOCK_CONCENTRATION_PCT:
            concentration.append(
                {
                    "kind": "stock",
                    "symbol": h.get("symbol"),
                    "name": h.get("company_name") or h.get("symbol"),
                    "pct": round(pct, 2),
                    "message": f"{h.get('symbol')} is {pct:.1f}% of the book (limit {STOCK_CONCENTRATION_PCT:.0f}%).",
                }
            )
    for sector, value in sector_map.items():
        pct = value / total * 100 if total else 0.0
        if pct > SECTOR_CONCENTRATION_PCT:
            concentration.append(
                {
                    "kind": "sector",
                    "sector": sector,
                    "pct": round(pct, 2),
                    "message": f"{sector} is {pct:.1f}% of the book (limit {SECTOR_CONCENTRATION_PCT:.0f}%).",
                }
            )

    quality = _quality_flags(rows)
    overlap = _fund_overlap(rows, total)
    tax = _tax_lots(rows, as_of)
    model = recommended_allocation(valuation_zone)
    overlap["_holdings_ref"] = rows
    drift = {
        "equity_pct": round(equity_pct, 2),
        "debt_pct": round(debt_pct, 2),
        "model_equity_pct": model["equity_pct"],
        "model_debt_pct": model["debt_pct"],
        "equity_drift_pct": round(equity_pct - model["equity_pct"], 2),
        "needs_rebalance": abs(equity_pct - model["equity_pct"]) > DRIFT_PCT,
    }

    suggestions = _suggestions(concentration, quality, overlap, drift, tax)
    overlap.pop("_holdings_ref", None)
    risk_score = _risk_score(concentration, quality, overlap, drift, debt_pct)

    return {
        "total_market_value": round(total, 2),
        "equity_to_debt_ratio": _ratio_label(equity_pct, debt_pct),
        "equity_pct": round(equity_pct, 2),
        "debt_pct": round(debt_pct, 2),
        "risk_score": risk_score,
        "sector_breakdown": [
            {
                "sector": k,
                "value": round(v, 2),
                "pct": round(v / total * 100, 2) if total else 0,
                "benchmark_pct": model["sector_benchmark"].get(k, model["unclassified_benchmark"]),
            }
            for k, v in sorted(sector_map.items(), key=lambda kv: -kv[1])
        ],
        "ideal_allocation": model,
        "concentration_warnings": concentration,
        "quality_flags": quality,
        "overlap": overlap,
        "tax": tax,
        "drift": drift,
        "suggestions": suggestions,
        "holdings": [
            {
                **h,
                "weight_pct": round(_num(h.get("market_value")) / total * 100, 2) if total else 0,
            }
            for h in rows
        ],
    }


def recommended_allocation(zone: str) -> dict:
    zone = (zone or "fair").lower()
    if zone == "undervalued":
        equity, debt = 75, 25
        badge = "Undervalued zone — SIPs can continue; prefer adding equity gradually."
    elif zone == "overvalued":
        equity, debt = 40, 60
        badge = "Overvalued zone — favour SIPs into debt/SGB and pause lump-sum equity."
    else:
        equity, debt = 60, 40
        badge = "Fair value zone — safe to continue SIPs."
        zone = "fair"
    return {
        "zone": zone,
        "equity_pct": equity,
        "debt_pct": debt,
        "badge": badge,
        "sector_benchmark": {
            "Banking": 18,
            "IT": 14,
            "Energy": 10,
            "FMCG": 9,
            "Auto": 7,
            "Pharma": 6,
            "Telecom": 4,
            "Infrastructure": 6,
            "Consumer": 6,
            "Index": 8,
            "Flexi Cap": 6,
            "Sovereign": 16,
        },
        "unclassified_benchmark": 5,
    }


def _quality_flags(rows: list) -> list:
    flags = []
    for h in rows:
        if (h.get("asset_type") or "").lower() != "equity":
            continue
        meta = STOCK_BY_SYMBOL.get((h.get("symbol") or "").upper(), {})
        if not meta:
            continue
        sector = (meta.get("sector") or "").lower()
        roce = _num(meta.get("roce"), 99)
        de = _num(meta.get("debt_to_equity"))
        pledge = _num(meta.get("promoter_pledge_pct"))
        if sector not in BANK_NBFC_SECTORS and roce < ROCE_FLOOR:
            flags.append(
                {
                    "symbol": meta["symbol"],
                    "rule": "roce",
                    "value": roce,
                    "message": f"{meta['symbol']} ROCE is {roce:.1f}% (long-term floor {ROCE_FLOOR:.0f}%).",
                }
            )
        if sector not in BANK_NBFC_SECTORS and de > DEBT_EQUITY_CEILING:
            flags.append(
                {
                    "symbol": meta["symbol"],
                    "rule": "debt_equity",
                    "value": de,
                    "message": f"{meta['symbol']} debt-to-equity is {de:.2f} (ceiling {DEBT_EQUITY_CEILING}).",
                }
            )
        if pledge > PLEDGE_CEILING:
            flags.append(
                {
                    "symbol": meta["symbol"],
                    "rule": "promoter_pledge",
                    "value": pledge,
                    "message": f"{meta['symbol']} promoter pledge is {pledge:.1f}% (ceiling {PLEDGE_CEILING:.0f}%).",
                }
            )
    return flags


def _fund_overlap(rows: list, total: float) -> dict:
    fund_rows = [h for h in rows if (h.get("asset_type") or "").lower() == "mutual_fund"]
    exposure: dict[str, dict] = {}
    for fund in fund_rows:
        key = scheme_key_from_name(fund.get("fund_name") or fund.get("company_name") or "")
        if not key:
            continue
        scheme = FUND_UNDERLYINGS[key]
        fund_value = _num(fund.get("market_value"))
        for symbol, weight in scheme["holdings"]:
            lookthrough = fund_value * (weight / 100.0)
            bucket = exposure.setdefault(
                symbol, {"symbol": symbol, "from_funds": [], "lookthrough_value": 0.0}
            )
            bucket["lookthrough_value"] += lookthrough
            bucket["from_funds"].append(
                {"fund": scheme["scheme_name"], "weight_in_fund_pct": weight, "value": round(lookthrough, 2)}
            )

    direct = {
        (h.get("symbol") or "").upper(): _num(h.get("market_value"))
        for h in rows
        if (h.get("asset_type") or "").lower() == "equity"
    }
    duplicates = []
    duplicated_value = 0.0
    for symbol, bucket in exposure.items():
        if symbol in direct and bucket["lookthrough_value"] > 0:
            duplicated_value += min(direct[symbol], bucket["lookthrough_value"])
            duplicates.append(
                {
                    "symbol": symbol,
                    "direct_value": round(direct[symbol], 2),
                    "fund_lookthrough_value": round(bucket["lookthrough_value"], 2),
                    "from_funds": bucket["from_funds"],
                }
            )

    # Fund-to-fund duplication (same stock in two schemes)
    fund_pairs = []
    symbols_in_multiple = [b for b in exposure.values() if len(b["from_funds"]) > 1]
    for bucket in symbols_in_multiple:
        fund_pairs.append(
            {
                "symbol": bucket["symbol"],
                "from_funds": bucket["from_funds"],
            }
        )

    overlap_pct = (duplicated_value / total * 100) if total else 0.0
    return {
        "overlap_pct": round(overlap_pct, 2),
        "duplicates": duplicates,
        "fund_to_fund": fund_pairs,
        "message": (
            f"About {overlap_pct:.1f}% of the book is the same stocks held both directly and inside equity funds."
            if duplicates
            else "No material stock duplication between direct equity and equity funds."
        ),
    }


def _tax_lots(rows: list, as_of: date) -> dict:
    lots = []
    harvestable = []
    for h in rows:
        qty = _num(h.get("quantity"))
        avg = _num(h.get("avg_price"))
        px = _num(h.get("current_price"))
        invested = qty * avg
        current = qty * px
        gain = current - invested
        bought = _holding_date(h.get("purchase_date"))
        days = (as_of - bought).days if bought else None
        asset = (h.get("asset_type") or "equity").lower()
        is_equity_like = asset in {"equity", "mutual_fund"}
        bucket = "LTCG" if (days is None or days >= LTCG_HOLDING_DAYS) and is_equity_like else "STCG"
        if asset == "debt":
            bucket = "slab"
        lot = {
            "symbol": h.get("symbol"),
            "gain": round(gain, 2),
            "bucket": bucket,
            "days_held": days,
        }
        lots.append(lot)
        if gain < -1000 and is_equity_like:
            harvestable.append(lot)
    ltcg = round(sum(l["gain"] for l in lots if l["bucket"] == "LTCG" and l["gain"] > 0), 2)
    stcg = round(sum(l["gain"] for l in lots if l["bucket"] == "STCG" and l["gain"] > 0), 2)
    return {"ltcg_unrealised": ltcg, "stcg_unrealised": stcg, "harvest_candidates": harvestable, "lots": lots}


def _suggestions(concentration, quality, overlap, drift, tax) -> list:
    cards = []
    if drift["needs_rebalance"] and drift["equity_drift_pct"] > 0:
        cards.append(
            {
                "code": "rebalance_equity_to_debt",
                "title": "Rebalance equity to debt",
                "body": (
                    f"Equity is {drift['equity_pct']:.0f}% vs a {drift['model_equity_pct']:.0f}% model. "
                    "Route the next SIP (and any tax-efficient trims) into G-Secs, RBI floating-rate bonds, or SDL target-maturity funds."
                ),
            }
        )
    if drift["needs_rebalance"] and drift["equity_drift_pct"] < 0:
        cards.append(
            {
                "code": "topup_equity_core",
                "title": "Top up the low-cost equity core",
                "body": "You are underweight equity versus the valuation-zone model. Prefer a Nifty 50 Direct index fund over adding another active scheme.",
            }
        )
    if any("regular" in (str(h.get("fund_name") or h.get("company_name") or "")).lower() for h in overlap.get("_holdings_ref") or []):
        cards.append(
            {
                "code": "switch_regular_to_direct",
                "title": "Switch high-cost Regular funds to Direct index funds",
                "body": "Regular plans pay a distributor commission for years. A Direct Nifty 50 / Midcap 150 fund keeps the same market, minus the leak.",
            }
        )
    if overlap.get("overlap_pct", 0) >= 5:
        cards.append(
            {
                "code": "reduce_overlap",
                "title": "Cut overlapping equity funds",
                "body": overlap["message"] + " Keep one low-cost index sleeve instead of two lookalike active funds.",
            }
        )
    if concentration:
        cards.append(
            {
                "code": "trim_concentration",
                "title": "Trim single-stock / single-sector concentration",
                "body": concentration[0]["message"] + " Size each company below 10% and each sector below 30%.",
            }
        )
    if quality:
        cards.append(
            {
                "code": "quality_audit",
                "title": "Review quality and leverage flags",
                "body": quality[0]["message"] + " These are long-term safety checks, not sell buttons.",
            }
        )
    if tax.get("harvest_candidates"):
        cards.append(
            {
                "code": "tax_loss_harvest",
                "title": "Consider tax-loss harvesting before you rebalance",
                "body": (
                    "Some lots are sitting on unrealised losses. Harvesting a loss against LTCG/STCG — then replacing with a similar index fund — can be more tax-efficient than a straight sale of winners."
                ),
            }
        )
    if not cards:
        cards.append(
            {
                "code": "stay_the_course",
                "title": "Stay the course",
                "body": "No material concentration, quality, or drift flags. Continue SIPs into the valuation-zone mix.",
            }
        )
    return cards


def _risk_score(concentration, quality, overlap, drift, debt_pct) -> dict:
    score = 82
    score -= 8 * len([c for c in concentration if c["kind"] == "stock"])
    score -= 6 * len([c for c in concentration if c["kind"] == "sector"])
    score -= 5 * len(quality)
    score -= int(min(overlap.get("overlap_pct", 0), 20) / 2)
    if drift["needs_rebalance"]:
        score -= 6
    if debt_pct < 10:
        score -= 4
    score = max(15, min(96, score))
    if score >= 75:
        label = "Healthy"
    elif score >= 55:
        label = "Needs attention"
    else:
        label = "Stretched"
    return {"score": score, "label": label}


def _ratio_label(equity_pct: float, debt_pct: float) -> str:
    if debt_pct <= 0:
        return f"{equity_pct:.0f}:0"
    return f"{equity_pct:.0f}:{debt_pct:.0f}"
