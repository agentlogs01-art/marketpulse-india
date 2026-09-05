"""Seeded NSE/BSE universe, fund underlyings, filings, and fixed-income cards."""

from typing import Optional
import re

STOCKS = [
    {
        "symbol": "RELIANCE",
        "nse_symbol": "RELIANCE",
        "bse_code": "500325",
        "company_name": "Reliance Industries Ltd",
        "sector": "Energy",
        "market_cap_category": "Large Cap",
        "pe": 26.4,
        "pe_5yr_median": 24.1,
        "roe": 9.8,
        "roce": 9.1,
        "debt_to_equity": 0.41,
        "fcf_crore": 18420,
        "dividend_yield": 0.35,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "RELIANCE.NS",
        "current_price": 2924.0,
        "week52_high": 3217.0,
        "week52_low": 2345.0,
    },
    {
        "symbol": "TCS",
        "nse_symbol": "TCS",
        "bse_code": "532755",
        "company_name": "Tata Consultancy Services Ltd",
        "sector": "IT",
        "market_cap_category": "Large Cap",
        "pe": 29.8,
        "pe_5yr_median": 28.4,
        "roe": 47.2,
        "roce": 58.6,
        "debt_to_equity": 0.09,
        "fcf_crore": 41200,
        "dividend_yield": 1.45,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "TCS.NS",
        "current_price": 3920.0,
        "week52_high": 4592.0,
        "week52_low": 3440.0,
    },
    {
        "symbol": "INFY",
        "nse_symbol": "INFY",
        "bse_code": "500209",
        "company_name": "Infosys Ltd",
        "sector": "IT",
        "market_cap_category": "Large Cap",
        "pe": 25.1,
        "pe_5yr_median": 24.8,
        "roe": 31.4,
        "roce": 39.2,
        "debt_to_equity": 0.11,
        "fcf_crore": 22800,
        "dividend_yield": 2.35,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "INFY.NS",
        "current_price": 1788.0,
        "week52_high": 2006.0,
        "week52_low": 1358.0,
    },
    {
        "symbol": "HDFCBANK",
        "nse_symbol": "HDFCBANK",
        "bse_code": "500180",
        "company_name": "HDFC Bank Ltd",
        "sector": "Banking",
        "market_cap_category": "Large Cap",
        "pe": 19.6,
        "pe_5yr_median": 19.2,
        "roe": 16.8,
        "roce": 7.4,
        "debt_to_equity": 6.85,
        "fcf_crore": -4200,
        "dividend_yield": 1.18,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "HDFCBANK.NS",
        "current_price": 1672.0,
        "week52_high": 1794.0,
        "week52_low": 1427.0,
    },
    {
        "symbol": "ICICIBANK",
        "nse_symbol": "ICICIBANK",
        "bse_code": "532174",
        "company_name": "ICICI Bank Ltd",
        "sector": "Banking",
        "market_cap_category": "Large Cap",
        "pe": 18.4,
        "pe_5yr_median": 17.9,
        "roe": 17.9,
        "roce": 7.1,
        "debt_to_equity": 6.12,
        "fcf_crore": 8900,
        "dividend_yield": 0.82,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "ICICIBANK.NS",
        "current_price": 1224.0,
        "week52_high": 1362.0,
        "week52_low": 1048.0,
    },
    {
        "symbol": "HINDUNILVR",
        "nse_symbol": "HINDUNILVR",
        "bse_code": "500696",
        "company_name": "Hindustan Unilever Ltd",
        "aliases": ["hul", "hindustan unilever"],
        "sector": "FMCG",
        "market_cap_category": "Large Cap",
        "pe": 54.2,
        "pe_5yr_median": 58.6,
        "roe": 19.8,
        "roce": 24.4,
        "debt_to_equity": 0.03,
        "fcf_crore": 9800,
        "dividend_yield": 1.72,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "HINDUNILVR.NS",
        "current_price": 2488.0,
        "week52_high": 3034.0,
        "week52_low": 2136.0,
    },
    {
        "symbol": "ITC",
        "nse_symbol": "ITC",
        "bse_code": "500875",
        "company_name": "ITC Ltd",
        "sector": "FMCG",
        "market_cap_category": "Large Cap",
        "pe": 27.6,
        "pe_5yr_median": 23.1,
        "roe": 28.4,
        "roce": 36.8,
        "debt_to_equity": 0.02,
        "fcf_crore": 15400,
        "dividend_yield": 3.05,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "ITC.NS",
        "current_price": 448.0,
        "week52_high": 528.0,
        "week52_low": 399.0,
    },
    {
        "symbol": "MARUTI",
        "nse_symbol": "MARUTI",
        "bse_code": "532500",
        "company_name": "Maruti Suzuki India Ltd",
        "sector": "Auto",
        "market_cap_category": "Large Cap",
        "pe": 26.8,
        "pe_5yr_median": 31.2,
        "roe": 16.4,
        "roce": 21.1,
        "debt_to_equity": 0.01,
        "fcf_crore": 7200,
        "dividend_yield": 1.08,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "MARUTI.NS",
        "current_price": 12840.0,
        "week52_high": 13700.0,
        "week52_low": 10725.0,
    },
    {
        "symbol": "TATAMOTORS",
        "nse_symbol": "TATAMOTORS",
        "bse_code": "500570",
        "company_name": "Tata Motors Ltd",
        "sector": "Auto",
        "market_cap_category": "Large Cap",
        "pe": 9.8,
        "pe_5yr_median": 14.6,
        "roe": 22.6,
        "roce": 16.8,
        "debt_to_equity": 0.62,
        "fcf_crore": 18600,
        "dividend_yield": 0.72,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "TATAMOTORS.NS",
        "current_price": 712.0,
        "week52_high": 1179.0,
        "week52_low": 551.0,
    },
    {
        "symbol": "SBIN",
        "nse_symbol": "SBIN",
        "bse_code": "500112",
        "company_name": "State Bank of India",
        "sector": "Banking",
        "market_cap_category": "Large Cap",
        "pe": 9.4,
        "pe_5yr_median": 10.8,
        "roe": 16.9,
        "roce": 6.4,
        "debt_to_equity": 13.4,
        "fcf_crore": 22100,
        "dividend_yield": 1.68,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "SBIN.NS",
        "current_price": 812.0,
        "week52_high": 912.0,
        "week52_low": 680.0,
    },
    {
        "symbol": "BHARTIARTL",
        "nse_symbol": "BHARTIARTL",
        "bse_code": "532454",
        "company_name": "Bharti Airtel Ltd",
        "sector": "Telecom",
        "market_cap_category": "Large Cap",
        "pe": 48.6,
        "pe_5yr_median": 52.0,
        "roe": 15.2,
        "roce": 13.8,
        "debt_to_equity": 1.72,
        "fcf_crore": 28400,
        "dividend_yield": 0.48,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "BHARTIARTL.NS",
        "current_price": 1648.0,
        "week52_high": 1779.0,
        "week52_low": 1234.0,
    },
    {
        "symbol": "ASIANPAINT",
        "nse_symbol": "ASIANPAINT",
        "bse_code": "500820",
        "company_name": "Asian Paints Ltd",
        "sector": "Consumer",
        "market_cap_category": "Large Cap",
        "pe": 52.4,
        "pe_5yr_median": 68.1,
        "roe": 26.8,
        "roce": 32.4,
        "debt_to_equity": 0.12,
        "fcf_crore": 4100,
        "dividend_yield": 1.12,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "ASIANPAINT.NS",
        "current_price": 2486.0,
        "week52_high": 3394.0,
        "week52_low": 2188.0,
    },
    {
        "symbol": "LT",
        "nse_symbol": "LT",
        "bse_code": "500510",
        "company_name": "Larsen & Toubro Ltd",
        "sector": "Infrastructure",
        "market_cap_category": "Large Cap",
        "pe": 32.1,
        "pe_5yr_median": 28.6,
        "roe": 16.4,
        "roce": 14.9,
        "debt_to_equity": 1.28,
        "fcf_crore": 9600,
        "dividend_yield": 0.92,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "LT.NS",
        "current_price": 3568.0,
        "week52_high": 3963.0,
        "week52_low": 2967.0,
    },
    {
        "symbol": "ADANIENT",
        "nse_symbol": "ADANIENT",
        "bse_code": "512599",
        "company_name": "Adani Enterprises Ltd",
        "sector": "Infrastructure",
        "market_cap_category": "Large Cap",
        "pe": 82.4,
        "pe_5yr_median": 64.0,
        "roe": 11.2,
        "roce": 9.4,
        "debt_to_equity": 1.68,
        "fcf_crore": -3200,
        "dividend_yield": 0.04,
        "promoter_pledge_pct": 16.8,
        "yahoo_symbol": "ADANIENT.NS",
        "current_price": 2488.0,
        "week52_high": 3743.0,
        "week52_low": 2025.0,
    },
    {
        "symbol": "IRFC",
        "nse_symbol": "IRFC",
        "bse_code": "543257",
        "company_name": "Indian Railway Finance Corp",
        "sector": "Financials",
        "market_cap_category": "Mid Cap",
        "pe": 24.6,
        "pe_5yr_median": 8.4,
        "roe": 12.8,
        "roce": 5.6,
        "debt_to_equity": 8.4,
        "fcf_crore": -18000,
        "dividend_yield": 1.42,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "IRFC.NS",
        "current_price": 142.0,
        "week52_high": 229.0,
        "week52_low": 108.0,
    },
    {
        "symbol": "DMART",
        "nse_symbol": "DMART",
        "bse_code": "540900",
        "company_name": "Avenue Supermarts Ltd",
        "sector": "Consumer",
        "market_cap_category": "Large Cap",
        "pe": 94.2,
        "pe_5yr_median": 108.0,
        "roe": 13.6,
        "roce": 16.8,
        "debt_to_equity": 0.04,
        "fcf_crore": 2100,
        "dividend_yield": 0.0,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "DMART.NS",
        "current_price": 4120.0,
        "week52_high": 5489.0,
        "week52_low": 3340.0,
    },
    {
        "symbol": "NESTLEIND",
        "nse_symbol": "NESTLEIND",
        "bse_code": "500790",
        "company_name": "Nestle India Ltd",
        "sector": "FMCG",
        "market_cap_category": "Large Cap",
        "pe": 72.8,
        "pe_5yr_median": 76.4,
        "roe": 92.4,
        "roce": 118.0,
        "debt_to_equity": 0.11,
        "fcf_crore": 2800,
        "dividend_yield": 1.28,
        "promoter_pledge_pct": 0.0,
        "yahoo_symbol": "NESTLEIND.NS",
        "current_price": 2388.0,
        "week52_high": 2777.0,
        "week52_low": 2115.0,
    },
    {
        "symbol": "SUNPHARMA",
        "nse_symbol": "SUNPHARMA",
        "bse_code": "524715",
        "company_name": "Sun Pharmaceutical Industries Ltd",
        "sector": "Pharma",
        "market_cap_category": "Large Cap",
        "pe": 38.4,
        "pe_5yr_median": 32.6,
        "roe": 16.2,
        "roce": 17.8,
        "debt_to_equity": 0.08,
        "fcf_crore": 8600,
        "dividend_yield": 0.82,
        "promoter_pledge_pct": 1.2,
        "yahoo_symbol": "SUNPHARMA.NS",
        "current_price": 1724.0,
        "week52_high": 1960.0,
        "week52_low": 1376.0,
    },
]

STOCK_BY_SYMBOL = {s["symbol"]: s for s in STOCKS}

FUND_UNDERLYINGS = {
    "nifty50_index_regular": {
        "scheme_name": "Nifty 50 Index Fund (Regular)",
        "holdings": [
            ("RELIANCE", 8.6),
            ("HDFCBANK", 13.1),
            ("ICICIBANK", 9.2),
            ("INFY", 6.4),
            ("TCS", 4.8),
            ("BHARTIARTL", 4.1),
            ("ITC", 3.6),
            ("LT", 3.4),
            ("SBIN", 3.2),
            ("HINDUNILVR", 2.4),
        ],
    },
    "nifty50_index_direct": {
        "scheme_name": "Nifty 50 Index Fund (Direct)",
        "holdings": [
            ("RELIANCE", 8.6),
            ("HDFCBANK", 13.1),
            ("ICICIBANK", 9.2),
            ("INFY", 6.4),
            ("TCS", 4.8),
            ("BHARTIARTL", 4.1),
            ("ITC", 3.6),
            ("LT", 3.4),
            ("SBIN", 3.2),
            ("HINDUNILVR", 2.4),
        ],
    },
    "flexi_cap_regular": {
        "scheme_name": "Flexi Cap Equity Fund (Regular)",
        "holdings": [
            ("HDFCBANK", 8.4),
            ("ICICIBANK", 7.1),
            ("RELIANCE", 6.8),
            ("INFY", 5.2),
            ("TCS", 4.4),
            ("MARUTI", 3.1),
            ("SUNPHARMA", 2.8),
        ],
    },
    "midcap_150_direct": {
        "scheme_name": "Nifty Midcap 150 Index Fund (Direct)",
        "holdings": [
            ("IRFC", 1.8),
            ("DMART", 2.2),
            ("SUNPHARMA", 1.4),
        ],
    },
}

FILINGS = {
    "TCS": [
        {
            "filed_at": "2026-07-12",
            "headline": "Board approves interim dividend of ₹10 per share",
            "body": "TCS announced an interim dividend funded from free cash flow.",
            "summary_3_5yr": "Cash returned to shareholders without stretching the balance sheet. For a 3–5 year holder this is a continuation of a high-ROE, low-debt compounding story rather than a one-off event.",
            "source": "NSE",
        },
        {
            "filed_at": "2026-04-18",
            "headline": "Q4 results: operating margin steady; large-deal TCV disclosed",
            "body": "Management highlighted deal pipeline and capital return policy.",
            "summary_3_5yr": "Margin stability plus large-deal TCV supports multi-year cash generation. Watch utilisation and wage inflation, not daily price noise.",
            "source": "BSE",
        },
    ],
    "RELIANCE": [
        {
            "filed_at": "2026-08-02",
            "headline": "Capex update on new energy and retail network expansion",
            "body": "Company filed a progress note on Jio/retail and new energy spend.",
            "summary_3_5yr": "Heavy capex can suppress near-term free cash flow while the new-energy book is still immature. Long-term holders should track ROCE trend, not headline revenue.",
            "source": "NSE",
        }
    ],
    "ADANIENT": [
        {
            "filed_at": "2026-06-21",
            "headline": "Update on promoter pledge and group leverage",
            "body": "Exchange filing restated promoter pledging and debt at holding-company level.",
            "summary_3_5yr": "Pledging above 15% plus elevated leverage is a multi-year governance and refinancing risk. Position size matters more than the next project announcement.",
            "source": "NSE",
        }
    ],
    "HDFCBANK": [
        {
            "filed_at": "2026-07-28",
            "headline": "Quarterly results: deposit growth and NIM commentary",
            "body": "Bank disclosed NII, NIM and slippages.",
            "summary_3_5yr": "For a 5-year SIP holder the question is franchise deposit share, not one quarter of NIM. Elevated debt-to-equity is normal for a bank and is scored separately from industrial leverage.",
            "source": "NSE",
        }
    ],
}

FIXED_INCOME = [
    {
        "id": "nifty50_index_direct",
        "name": "Nifty 50 Index Fund (Direct)",
        "category": "Index equity",
        "ytm": None,
        "expense_ratio": 0.10,
        "safety_badge": "Market risk · lowest cost equity core",
        "tax_rules": "Equity LTCG above ₹1.25 lakh at 12.5% after 12 months.",
        "notes": "Default long-term equity building block. Prefer Direct over Regular.",
    },
    {
        "id": "midcap150_index_direct",
        "name": "Nifty Midcap 150 Index Fund (Direct)",
        "category": "Index equity",
        "ytm": None,
        "expense_ratio": 0.18,
        "safety_badge": "Higher cycle risk than Nifty 50",
        "tax_rules": "Same equity capital-gains treatment as Nifty 50 funds.",
        "notes": "Satellite sleeve. Keep sizing modest versus the Nifty 50 core.",
    },
    {
        "id": "rbi_frb",
        "name": "RBI Floating Rate Savings Bonds",
        "category": "Sovereign debt",
        "ytm": 8.05,
        "expense_ratio": 0.0,
        "safety_badge": "Sovereign",
        "tax_rules": "Interest is taxable as per slab. No LTCG. 7-year lock-in.",
        "notes": "Rate resets every 6 months vs NSC. Suitable for the secured-debt bucket.",
    },
    {
        "id": "sgb_primary",
        "name": "Sovereign Gold Bonds (primary / secondary)",
        "category": "Sovereign gold",
        "ytm": 2.50,
        "expense_ratio": 0.0,
        "safety_badge": "Sovereign",
        "tax_rules": "2.5% annual interest taxable. Capital gains on redemption after 8 years are tax-exempt if held to maturity.",
        "notes": "Prefer SGB over physical gold. Check secondary-market discount vs IBJA spot.",
    },
    {
        "id": "sdl_target_maturity",
        "name": "Target Maturity SDL Index Fund",
        "category": "AAA / sovereign-linked debt",
        "ytm": 7.15,
        "expense_ratio": 0.15,
        "safety_badge": "AAA / State guaranteed pool",
        "tax_rules": "Debt fund taxation: gains added to income as per slab (post Apr 2023 acquisitions).",
        "notes": "Hold to target date to harvest YTM. Avoid trading the NAV.",
    },
    {
        "id": "gsec_10y",
        "name": "10-Year Government of India G-Sec",
        "category": "Sovereign debt",
        "ytm": 6.92,
        "expense_ratio": 0.0,
        "safety_badge": "Sovereign",
        "tax_rules": "Interest taxed as income. Listed G-Secs can be held via gilt funds or RBI Retail Direct.",
        "notes": "Benchmark for the secured-debt allocation.",
    },
]

# Educational sample of sovereign and secured issues commonly used in a
# long-term debt sleeve. Not a live exchange dump of every outstanding ISIN.
SECURED_BONDS = [
    {
        "id": "rbi_frb_taxable",
        "name": "RBI Floating Rate Savings Bonds 2020 (Taxable)",
        "issuer_type": "RBI Bond",
        "coupon_pct": 8.05,
        "tenure_years": 7,
        "ytm": 8.05,
        "issued_on": "2020-07-01",
        "rating": "Sovereign",
        "notes": "Rate resets every 6 months. 7-year lock-in. Interest taxed at slab.",
    },
    {
        "id": "goi_gsec_2034",
        "name": "GOI 7.18% 2034 G-Sec",
        "issuer_type": "Central government",
        "coupon_pct": 7.18,
        "tenure_years": 8,
        "ytm": 6.92,
        "issued_on": "2024-07-22",
        "rating": "Sovereign",
        "notes": "Benchmark sovereign. Hold via RBI Retail Direct or a gilt fund.",
    },
    {
        "id": "goi_gsec_2064",
        "name": "GOI 7.09% 2064 G-Sec",
        "issuer_type": "Central government",
        "coupon_pct": 7.09,
        "tenure_years": 38,
        "ytm": 7.04,
        "issued_on": "2024-01-15",
        "rating": "Sovereign",
        "notes": "Ultra-long gilt. Duration risk is high; size modestly.",
    },
    {
        "id": "sdl_mh_2034",
        "name": "Maharashtra SDL 7.32% 2034",
        "issuer_type": "State government",
        "coupon_pct": 7.32,
        "tenure_years": 10,
        "ytm": 7.22,
        "issued_on": "2024-03-12",
        "rating": "Sovereign (state)",
        "notes": "State development loan. Typically 20–40 bps over G-Sec of similar tenor.",
    },
    {
        "id": "sdl_tn_2033",
        "name": "Tamil Nadu SDL 7.41% 2033",
        "issuer_type": "State government",
        "coupon_pct": 7.41,
        "tenure_years": 9,
        "ytm": 7.28,
        "issued_on": "2024-02-06",
        "rating": "Sovereign (state)",
        "notes": "SDL cash-flows are state-backed. Prefer a ladder of maturities.",
    },
    {
        "id": "sdl_gj_2036",
        "name": "Gujarat SDL 7.25% 2036",
        "issuer_type": "State government",
        "coupon_pct": 7.25,
        "tenure_years": 12,
        "ytm": 7.19,
        "issued_on": "2024-05-21",
        "rating": "Sovereign (state)",
        "notes": "Stronger-state SDL. Still mark-to-market if not held to maturity.",
    },
    {
        "id": "sdl_ka_2032",
        "name": "Karnataka SDL 7.38% 2032",
        "issuer_type": "State government",
        "coupon_pct": 7.38,
        "tenure_years": 8,
        "ytm": 7.21,
        "issued_on": "2024-04-16",
        "rating": "Sovereign (state)",
        "notes": "Use inside the secured-debt bucket, not as a trading sleeve.",
    },
    {
        "id": "nhai_ncd_2029",
        "name": "NHAI 7.60% Secured NCD 2029",
        "issuer_type": "Corporate (AAA PSU)",
        "coupon_pct": 7.60,
        "tenure_years": 5,
        "ytm": 7.35,
        "issued_on": "2024-06-10",
        "rating": "CRISIL AAA / ICRA AAA",
        "notes": "Secured against NHAI assets. PSU infrastructure credit.",
    },
    {
        "id": "rec_ncd_2031",
        "name": "REC 7.72% Secured NCD 2031",
        "issuer_type": "Corporate (AAA PSU)",
        "coupon_pct": 7.72,
        "tenure_years": 7,
        "ytm": 7.48,
        "issued_on": "2024-08-19",
        "rating": "CRISIL AAA / CARE AAA",
        "notes": "Power-sector PSU. Treat as AAA corporate, not G-Sec.",
    },
    {
        "id": "pfc_ncd_2030",
        "name": "PFC 7.68% Secured NCD 2030",
        "issuer_type": "Corporate (AAA PSU)",
        "coupon_pct": 7.68,
        "tenure_years": 6,
        "ytm": 7.44,
        "issued_on": "2024-09-03",
        "rating": "CRISIL AAA / ICRA AAA",
        "notes": "Secured NCD. Liquidity is thinner than G-Sec; hold to cash-flow dates.",
    },
    {
        "id": "irfc_ncd_2032",
        "name": "IRFC 7.45% Secured NCD 2032",
        "issuer_type": "Corporate (AAA PSU)",
        "coupon_pct": 7.45,
        "tenure_years": 8,
        "ytm": 7.30,
        "issued_on": "2024-01-29",
        "rating": "CRISIL AAA",
        "notes": "Railway finance PSU. Coupon is taxable at slab unless held in a tax-free vintage.",
    },
    {
        "id": "hudco_ncd_2028",
        "name": "HUDCO 7.55% Secured NCD 2028",
        "issuer_type": "Corporate (AAA PSU)",
        "coupon_pct": 7.55,
        "tenure_years": 4,
        "ytm": 7.28,
        "issued_on": "2024-11-12",
        "rating": "ICRA AAA / CARE AAA",
        "notes": "Housing PSU secured paper. Keep issuer concentration low.",
    },
    {
        "id": "hdfc_ncd_2029",
        "name": "HDFC Ltd 7.80% Secured NCD 2029",
        "issuer_type": "Corporate (AAA)",
        "coupon_pct": 7.80,
        "tenure_years": 5,
        "ytm": 7.52,
        "issued_on": "2023-12-18",
        "rating": "CRISIL AAA / ICRA AAA",
        "notes": "Housing-finance secured NCD. Credit is strong; still not sovereign.",
    },
    {
        "id": "lt_ncd_2030",
        "name": "L&T 7.70% Secured NCD 2030",
        "issuer_type": "Corporate (AAA)",
        "coupon_pct": 7.70,
        "tenure_years": 6,
        "ytm": 7.40,
        "issued_on": "2024-02-28",
        "rating": "CRISIL AAA",
        "notes": "Industrial conglomerate secured NCD. Check remaining face value on NSE/BSE.",
    },
    {
        "id": "bajaj_ncd_2027",
        "name": "Bajaj Finance 8.05% Secured NCD 2027",
        "issuer_type": "Corporate (AAA)",
        "coupon_pct": 8.05,
        "tenure_years": 3,
        "ytm": 7.62,
        "issued_on": "2024-10-07",
        "rating": "CRISIL AAA / ICRA AAA",
        "notes": "NBFC secured NCD. Higher coupon vs G-Sec compensates for credit and liquidity.",
    },
]

SGB_SERIES = [
    {
        "series": "SGBNOV27",
        "nse_symbol": "SGBNOV27",
        "market_price": 7245.0,
        "gold_spot_inr": 7620.0,
        "discount_pct": 4.92,
        "maturity": "2027-11-30",
    },
    {
        "series": "SGBDEC28",
        "nse_symbol": "SGBDEC28",
        "market_price": 7510.0,
        "gold_spot_inr": 7620.0,
        "discount_pct": 1.44,
        "maturity": "2028-12-17",
    },
    {
        "series": "SGBFEB31",
        "nse_symbol": "SGBFEB31",
        "market_price": 7688.0,
        "gold_spot_inr": 7620.0,
        "discount_pct": -0.89,
        "maturity": "2031-02-24",
    },
]

DEFAULT_VALUATION = {
    "nifty_pe": 21.8,
    "nifty_pb": 3.6,
    "dividend_yield": 1.22,
    "market_cap_to_gdp": 1.18,
    "nifty50_level": 24780.0,
    "smallcap250_level": 16840.0,
    "gsec_10y_yield": 6.92,
}

BROKER_DEMO_HOLDINGS = [
    {
        "symbol": "HDFCBANK",
        "company_name": "HDFC Bank Ltd",
        "asset_type": "equity",
        "sector": "Banking",
        "quantity": 40,
        "avg_price": 1480,
        "current_price": 1672,
        "fund_name": None,
        "isin": "INE040A01034",
        "purchase_date": "2023-02-11",
    },
    {
        "symbol": "TCS",
        "company_name": "Tata Consultancy Services Ltd",
        "asset_type": "equity",
        "sector": "IT",
        "quantity": 12,
        "avg_price": 3600,
        "current_price": 3920,
        "fund_name": None,
        "isin": "INE467B01029",
        "purchase_date": "2022-11-03",
    },
    {
        "symbol": "ADANIENT",
        "company_name": "Adani Enterprises Ltd",
        "asset_type": "equity",
        "sector": "Infrastructure",
        "quantity": 18,
        "avg_price": 2100,
        "current_price": 2488,
        "fund_name": None,
        "isin": "INE423A01024",
        "purchase_date": "2024-01-19",
    },
    {
        "symbol": "NIFTY50REG",
        "company_name": "Nifty 50 Index Fund (Regular)",
        "asset_type": "mutual_fund",
        "sector": "Index",
        "quantity": 820,
        "avg_price": 148,
        "current_price": 176,
        "fund_name": "Nifty 50 Index Fund (Regular)",
        "isin": "INF000NIFTYR",
        "purchase_date": "2021-08-01",
    },
    {
        "symbol": "FLEXIREG",
        "company_name": "Flexi Cap Equity Fund (Regular)",
        "asset_type": "mutual_fund",
        "sector": "Flexi Cap",
        "quantity": 640,
        "avg_price": 92,
        "current_price": 118,
        "fund_name": "Flexi Cap Equity Fund (Regular)",
        "isin": "INF000FLEXIR",
        "purchase_date": "2022-04-15",
    },
    {
        "symbol": "GSEC10",
        "company_name": "10-Year G-Sec allocation",
        "asset_type": "debt",
        "sector": "Sovereign",
        "quantity": 80,
        "avg_price": 98.4,
        "current_price": 101.2,
        "fund_name": None,
        "isin": "IN002023GSEC",
        "purchase_date": "2024-06-01",
    },
]


def enrich_holding(row: dict) -> dict:
    symbol = (row.get("symbol") or "").upper().strip()
    meta = STOCK_BY_SYMBOL.get(symbol, {})
    qty = float(row.get("quantity") or 0)
    avg = float(row.get("avg_price") or 0)
    px = float(row.get("current_price") or meta.get("current_price") or avg or 0)
    out = dict(row)
    out["symbol"] = symbol or out.get("fund_name") or "UNKNOWN"
    out["company_name"] = out.get("company_name") or meta.get("company_name")
    out["sector"] = out.get("sector") or meta.get("sector") or "Unclassified"
    out["current_price"] = px
    out["avg_price"] = avg
    out["quantity"] = qty
    out["market_value"] = round(qty * px, 2)
    out["asset_type"] = (out.get("asset_type") or "equity").lower()
    return out


def search_stocks(query: str, limit: int = 10) -> list:
    q = (query or "").strip().lower()
    q = q.replace(".ns", "").replace(".bo", "").replace(" nse", "").replace(" bse", "")
    if not q:
        return STOCKS[:limit]
    tokens = [t for t in re.split(r"[\s,]+", q) if t]
    scored = []
    for row in STOCKS:
        symbol = (row.get("symbol") or "").lower()
        nse = (row.get("nse_symbol") or "").lower()
        hay = " ".join(
            [
                row.get("symbol") or "",
                row.get("nse_symbol") or "",
                row.get("bse_code") or "",
                row.get("company_name") or "",
                " ".join(row.get("aliases") or []),
            ]
        ).lower()
        if q in hay or all(t in hay for t in tokens):
            exact = 0 if q in {symbol, nse} else 1
            prefix = 0 if symbol.startswith(q) or nse.startswith(q) else 1
            scored.append((exact, prefix, row))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored[:limit]]


def get_stock(symbol: str) -> Optional[dict]:
    raw = (symbol or "").upper().strip()
    raw = raw.replace(".NS", "").replace(".BO", "")
    hit = STOCK_BY_SYMBOL.get(raw)
    if hit:
        return hit
    for row in STOCKS:
        aliases = [a.upper() for a in (row.get("aliases") or [])]
        if raw in aliases:
            return row
    return None


def filings_for(symbol: str) -> list:
    return list(FILINGS.get((symbol or "").upper().strip(), []))


def scheme_key_from_name(name: str) -> Optional[str]:
    n = (name or "").lower()
    if "midcap 150" in n or "midcap150" in n:
        return "midcap_150_direct"
    if "nifty 50" in n and "direct" in n:
        return "nifty50_index_direct"
    if "nifty 50" in n:
        return "nifty50_index_regular"
    if "flexi" in n:
        return "flexi_cap_regular"
    return None


def _median(values: list) -> Optional[float]:
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return round(vals[mid], 2)
    return round((vals[mid - 1] + vals[mid]) / 2, 2)


def week52_context(stock: dict) -> dict:
    lo = float(stock.get("week52_low") or 0)
    hi = float(stock.get("week52_high") or 0)
    px = float(stock.get("current_price") or 0)
    span = hi - lo
    from_low_pct = round(((px - lo) / lo) * 100, 2) if lo else None
    from_high_pct = round(((px - hi) / hi) * 100, 2) if hi else None
    range_pct = round(((px - lo) / span) * 100, 1) if span else None
    if range_pct is None:
        direction = "flat"
    elif range_pct >= 55:
        direction = "up"
    elif range_pct <= 45:
        direction = "down"
    else:
        direction = "flat"
    return {
        "low": lo,
        "high": hi,
        "price": px,
        "from_low_pct": from_low_pct,
        "from_high_pct": from_high_pct,
        "range_pct": range_pct,
        "direction": direction,
    }


def _sector_metric_keys(sector: str) -> list:
    s = (sector or "").lower()
    if s in {"banking", "financials", "nbfc"}:
        return [
            ("roe", "ROE", "%"),
            ("dividend_yield", "Dividend yield", "%"),
        ]
    if s in {"it", "fmcg", "consumer", "pharma", "auto"}:
        return [
            ("roe", "ROE", "%"),
            ("roce", "ROCE", "%"),
            ("fcf_crore", "FCF (₹ cr)", ""),
            ("dividend_yield", "Dividend yield", "%"),
        ]
    return [
        ("roe", "ROE", "%"),
        ("roce", "ROCE", "%"),
        ("fcf_crore", "FCF (₹ cr)", ""),
        ("dividend_yield", "Dividend yield", "%"),
    ]


def sector_metric_deltas(stock: dict) -> list:
    sector = stock.get("sector") or ""
    peers = [row for row in STOCKS if (row.get("sector") or "") == sector]
    out = []
    for key, label, unit in _sector_metric_keys(sector):
        value = stock.get(key)
        median = _median([p.get(key) for p in peers])
        delta_pct = None
        if value is not None and median not in (None, 0):
            delta_pct = round(((float(value) - float(median)) / abs(float(median))) * 100, 1)
        direction = "flat"
        if delta_pct is not None and delta_pct > 0.5:
            direction = "up"
        elif delta_pct is not None and delta_pct < -0.5:
            direction = "down"
        out.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "value": value,
                "sector_median": median,
                "delta_pct": delta_pct,
                "direction": direction,
            }
        )
    return out
