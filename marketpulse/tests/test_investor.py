"""Tests for additive investor engines and /api/v1 handlers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from marketpulse.api import investor_handlers
from marketpulse.investor.cas_parser import parse_holdings_payload
from marketpulse.investor.crypto import decrypt_holdings_blob, encrypt_holdings_blob
from marketpulse.investor.diagnostics import analyze_portfolio
from marketpulse.investor.valuation import classify_zone
from marketpulse.tests.test_api_handlers import ApiHandlersTestCase


class TestValuationZone(unittest.TestCase):
    def test_fair_mid_range(self):
        self.assertEqual(classify_zone(21.5, 1.05), "fair")

    def test_undervalued(self):
        self.assertEqual(classify_zone(16.0, 0.8), "undervalued")

    def test_overvalued(self):
        self.assertEqual(classify_zone(28.0, 1.4), "overvalued")


class TestCasParser(unittest.TestCase):
    def test_csv_columns(self):
        csv = (
            "symbol,quantity,avg_price,current_price,sector\n"
            "TCS,10,3000,3920,IT\n"
            "ADANIENT,20,2000,2488,Infrastructure\n"
        )
        parsed = parse_holdings_payload(csv.encode(), filename="cas.csv")
        self.assertEqual(parsed["source"], "cas_excel")
        self.assertEqual(len(parsed["holdings"]), 2)
        self.assertEqual(parsed["holdings"][0]["symbol"], "TCS")

    def test_broker_token_demo(self):
        parsed = parse_holdings_payload(b"", broker_token="aa-link")
        self.assertEqual(parsed["source"], "broker_aa")
        self.assertGreater(len(parsed["holdings"]), 3)


class TestDiagnostics(unittest.TestCase):
    def test_concentration_and_pledge(self):
        holdings = [
            {
                "symbol": "ADANIENT",
                "company_name": "Adani Enterprises Ltd",
                "asset_type": "equity",
                "sector": "Infrastructure",
                "quantity": 100,
                "avg_price": 2000,
                "current_price": 2488,
                "market_value": 248800,
            },
            {
                "symbol": "ITC",
                "company_name": "ITC Ltd",
                "asset_type": "equity",
                "sector": "FMCG",
                "quantity": 10,
                "avg_price": 400,
                "current_price": 448,
                "market_value": 4480,
            },
        ]
        report = analyze_portfolio(holdings, valuation_zone="fair")
        self.assertTrue(any(w["kind"] == "stock" for w in report["concentration_warnings"]))
        self.assertTrue(any(f["rule"] == "promoter_pledge" for f in report["quality_flags"]))
        self.assertGreaterEqual(report["overlap"]["overlap_pct"], 0)

    def test_fund_overlap(self):
        holdings = [
            {
                "symbol": "HDFCBANK",
                "company_name": "HDFC Bank Ltd",
                "asset_type": "equity",
                "sector": "Banking",
                "quantity": 50,
                "avg_price": 1500,
                "current_price": 1672,
                "market_value": 83600,
            },
            {
                "symbol": "NIFTY50REG",
                "company_name": "Nifty 50 Index Fund (Regular)",
                "asset_type": "mutual_fund",
                "sector": "Index",
                "quantity": 500,
                "avg_price": 100,
                "current_price": 176,
                "market_value": 88000,
                "fund_name": "Nifty 50 Index Fund (Regular)",
            },
        ]
        report = analyze_portfolio(holdings, valuation_zone="overvalued")
        self.assertGreater(report["overlap"]["overlap_pct"], 0)
        codes = {s["code"] for s in report["suggestions"]}
        self.assertIn("switch_regular_to_direct", codes)


class TestCryptoRoundTrip(unittest.TestCase):
    def test_encrypt_decrypt(self):
        payload = [{"symbol": "TCS", "quantity": 1}]
        blob = encrypt_holdings_blob(payload)
        self.assertTrue(blob.startswith("aes256gcm:") or blob.startswith("xorhmac:"))
        self.assertEqual(decrypt_holdings_blob(blob), payload)


class TestInvestorApi(ApiHandlersTestCase):
    def test_v1_requires_session(self):
        with self.assertRaises(Exception):
            investor_handlers.get_valuation_zone("")

    def test_upload_and_analysis(self):
        token = self._signup_verify_and_login("investor@example.com")
        csv = "symbol,quantity,avg_price,current_price,sector\nTCS,10,3000,3920,IT\nRELIANCE,5,2800,2924,Energy\n"
        uploaded = investor_handlers.upload_portfolio(token, raw=csv.encode(), filename="book.csv")
        self.assertTrue(uploaded["ok"])
        self.assertEqual(uploaded["holdings_count"], 2)
        analysis = investor_handlers.get_portfolio_analysis(token)
        self.assertTrue(analysis["ok"])
        self.assertFalse(analysis["empty"])
        self.assertIn("risk_score", analysis["analysis"])

    def test_stock_search_and_detail(self):
        token = self._signup_verify_and_login("lookup@example.com")
        hits = investor_handlers.search_stock_symbols(token, "infosys")
        self.assertTrue(any(r["symbol"] == "INFY" for r in hits["results"]))
        hul = investor_handlers.search_stock_symbols(token, "Hindustan Unilever")
        self.assertTrue(any(r["symbol"] == "HINDUNILVR" for r in hul["results"]))
        ticker = investor_handlers.search_stock_symbols(token, "INFY.NS")
        self.assertTrue(any(r["symbol"] == "INFY" for r in ticker["results"]))
        with patch("marketpulse.pipeline.market_data.fetch_quote", side_effect=RuntimeError("offline")):
            detail = investor_handlers.get_stock_detail(token, "INFY")
            hul_detail = investor_handlers.get_stock_detail(token, "HUL")
            tcs = investor_handlers.get_stock_detail(token, "TCS")
        self.assertEqual(detail["stock"]["nse_symbol"], "INFY")
        self.assertEqual(hul_detail["stock"]["symbol"], "HINDUNILVR")
        self.assertIn("filings", detail["stock"])
        self.assertIn("from_low_pct", detail["stock"]["week52"])
        self.assertTrue(detail["stock"]["metric_deltas"])
        self.assertEqual(tcs["stock"]["symbol"], "TCS")
        fav = investor_handlers.set_ticker_favorite(token, "INFY", True)
        self.assertTrue(any(r["symbol"] == "INFY" for r in fav["favorites"]))
        watch = investor_handlers.get_ticker_watchlist(token)
        self.assertTrue(any(r["symbol"] == "TCS" for r in watch["recents"]))

    def test_valuation_and_fixed_income(self):
        token = self._signup_verify_and_login("zone@example.com")
        zone = investor_handlers.get_valuation_zone(token)
        self.assertIn(zone["zone"], {"undervalued", "fair", "overvalued"})
        self.assertIn("recommended_allocation", zone)
        fi = investor_handlers.get_secured_fixed_income(token)
        self.assertTrue(fi["instruments"])
        self.assertTrue(fi["sgb_discount_highlight"]["discount_pct"] > 0)
        kinds = {b["issuer_type"] for b in fi["secured_bonds"]}
        self.assertIn("RBI Bond", kinds)
        self.assertIn("State government", kinds)
        self.assertTrue(any("Corporate" in k for k in kinds))
        self.assertTrue(all("coupon_pct" in b and "issued_on" in b and "rating" in b for b in fi["secured_bonds"]))

    def test_legacy_login_still_works(self):
        from marketpulse.api import handlers

        token = self._signup_verify_and_login("legacy@example.com")
        me = handlers.get_current_subscriber(token)
        self.assertEqual(me["subscriber"]["email"], "legacy@example.com")


if __name__ == "__main__":
    unittest.main()
