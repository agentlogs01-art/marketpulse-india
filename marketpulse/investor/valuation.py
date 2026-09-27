"""Nifty valuation zone from P/E and market-cap-to-GDP."""

from __future__ import annotations

from datetime import date
from typing import Optional

from marketpulse.investor.catalog import get_default_valuation
from marketpulse.investor.diagnostics import recommended_allocation


def classify_zone(nifty_pe: float, market_cap_to_gdp: float) -> str:
    """Blend of Nifty 50 P/E and Buffett-style cap-to-GDP."""
    pe_score = 0
    if nifty_pe < 18:
        pe_score = -1
    elif nifty_pe > 24:
        pe_score = 1
    cap_score = 0
    if market_cap_to_gdp < 0.90:
        cap_score = -1
    elif market_cap_to_gdp > 1.20:
        cap_score = 1
    blended = pe_score + cap_score
    if blended <= -1:
        return "undervalued"
    if blended >= 2 or (pe_score == 1 and cap_score == 1):
        return "overvalued"
    if blended >= 1:
        return "overvalued"
    return "fair"


def build_valuation_snapshot(overrides: Optional[dict] = None) -> dict:
    data = dict(get_default_valuation())
    if overrides:
        data.update({k: v for k, v in overrides.items() if v is not None})
    zone = classify_zone(float(data["nifty_pe"]), float(data["market_cap_to_gdp"]))
    model = recommended_allocation(zone)
    return {
        "as_of_date": date.today().isoformat(),
        "nifty_pe": data["nifty_pe"],
        "nifty_pb": data["nifty_pb"],
        "dividend_yield": data["dividend_yield"],
        "market_cap_to_gdp": data["market_cap_to_gdp"],
        "zone": zone,
        "zone_badge": model["badge"],
        "nifty50_level": data["nifty50_level"],
        "smallcap250_level": data["smallcap250_level"],
        "gsec_10y_yield": data["gsec_10y_yield"],
        "recommended_allocation": {
            "equity_pct": model["equity_pct"],
            "debt_pct": model["debt_pct"],
        },
        "source": data.get("source", "seed"),
    }
