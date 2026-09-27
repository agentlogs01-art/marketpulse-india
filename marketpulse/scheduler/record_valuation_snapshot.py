"""Post-market valuation snapshot job (additive; does not alter the briefing pipeline)."""

from __future__ import annotations

from marketpulse.investor.repo import upsert_valuation
from marketpulse.investor.valuation import build_valuation_snapshot


def record_valuation_snapshot(overrides=None) -> dict:
    snap = build_valuation_snapshot(overrides)
    upsert_valuation(snap)
    return snap


if __name__ == "__main__":
    print(record_valuation_snapshot())
