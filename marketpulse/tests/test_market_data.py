"""
tests/test_market_data.py

Instrument snapshots must not silently become 0.00 / 0% when Yahoo
rejects a headerless request — Stooq is the CI fallback.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.pipeline.market_data import (
    fetch_instrument_snapshot,
    format_market_context_for_llm,
    parse_stooq_csv,
)
from marketpulse.models.schemas import GiftNiftySnapshot, InstrumentSnapshot


STOOQ_CSV = """Symbol,Date,Time,Open,High,Low,Close,Volume
^DJI,2026-08-27,22:00:00,39400.10,39600.00,39300.00,39550.25,12345
"""

YAHOO_CHART = {
    "chart": {
        "result": [
            {
                "meta": {
                    "regularMarketPrice": 39550.25,
                    "previousClose": 39400.10,
                    "chartPreviousClose": 39400.10,
                },
                "indicators": {"quote": [{"close": [39400.10, 39550.25]}]},
            }
        ]
    }
}


class TestParseStooqCsv(unittest.TestCase):
    def test_reads_last_close(self):
        quote = parse_stooq_csv(STOOQ_CSV)
        self.assertAlmostEqual(quote["price"], 39550.25)
        self.assertAlmostEqual(quote["previous_close"], 39400.10)

    def test_skips_na_rows(self):
        csv = (
            "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
            "^DJI,2026-08-28,22:00:00,N/A,N/A,N/A,N/A,N/A\n"
            "^DJI,2026-08-27,22:00:00,39400.10,39600.00,39300.00,39550.25,12345\n"
        )
        quote = parse_stooq_csv(csv)
        self.assertAlmostEqual(quote["price"], 39550.25)


class TestFetchInstrumentSnapshot(unittest.TestCase):
    spec = {
        "name": "Dow Jones (US)",
        "unit": "index pts",
        "yahoo_symbol": "^DJI",
        "stooq_symbol": "^dji",
    }

    @patch("marketpulse.pipeline.market_data._stooq_quote")
    @patch("marketpulse.pipeline.market_data._yahoo_chart_quote")
    def test_uses_yahoo_when_available(self, mock_yahoo, mock_stooq):
        mock_yahoo.return_value = {
            "price": 39550.25,
            "previous_close": 39400.10,
            "source": "Yahoo Finance (^DJI)",
        }
        snap = fetch_instrument_snapshot(self.spec)
        self.assertAlmostEqual(snap.value, 39550.25)
        self.assertGreater(abs(snap.pct_change), 0.0)
        mock_stooq.assert_not_called()

    @patch("marketpulse.pipeline.market_data._stooq_quote")
    @patch("marketpulse.pipeline.market_data._yahoo_chart_quote")
    def test_falls_back_to_stooq_instead_of_zeros(self, mock_yahoo, mock_stooq):
        mock_yahoo.side_effect = RuntimeError("401 Unauthorized")
        mock_stooq.return_value = {
            "price": 39550.25,
            "previous_close": 39400.10,
            "source": "Stooq (^dji)",
        }
        snap = fetch_instrument_snapshot(self.spec)
        self.assertAlmostEqual(snap.value, 39550.25)
        self.assertNotEqual(snap.pct_change, 0.0)
        self.assertNotEqual(snap.source, "unavailable")

    @patch("marketpulse.pipeline.market_data._stooq_quote")
    @patch("marketpulse.pipeline.market_data._yahoo_chart_quote")
    def test_zeros_only_when_all_sources_fail(self, mock_yahoo, mock_stooq):
        mock_yahoo.side_effect = RuntimeError("401")
        mock_stooq.side_effect = RuntimeError("timeout")
        snap = fetch_instrument_snapshot(self.spec)
        self.assertEqual(snap.value, 0.0)
        self.assertEqual(snap.pct_change, 0.0)
        self.assertTrue(snap.is_delayed)


class TestMarketContextForLlm(unittest.TestCase):
    def test_omits_zeroed_instruments(self):
        gift = GiftNiftySnapshot(
            last_traded_price=24850.5,
            pct_change_vs_prev_close=0.21,
            prev_nifty_close=24800.0,
            captured_at_ist="2026-08-28T01:15:00+00:00",
            source="Yahoo Finance (^NSEI)",
        )
        snapshots = [
            InstrumentSnapshot(name="Dow Jones (US)", value=39550.25, pct_change=0.38, unit="index pts"),
            InstrumentSnapshot(name="Nasdaq (US)", value=0.0, pct_change=0.0, unit="index pts"),
        ]
        text = format_market_context_for_llm(gift, snapshots)
        self.assertIn("24850.50", text)
        self.assertIn("Dow Jones (US)", text)
        self.assertNotIn("Nasdaq (US)", text)


if __name__ == "__main__":
    unittest.main()
