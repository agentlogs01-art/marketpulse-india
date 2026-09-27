"""Dynamic NSE/BSE universe, live quotes, and request-time fixed-income cards.

Nothing is fetched at import time so Flask can boot without NSE/BSE/Yahoo.
"""

from __future__ import annotations

import csv
import io
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

# Name/ticker hints so search still works if the exchange CSV is unreachable.
# Prices and ratios always come from live fetchers, never from this table.
_SEARCH_HINTS = [
    {"symbol": "INFY", "nse_symbol": "INFY", "company_name": "Infosys Ltd", "aliases": ["infosys"], "yahoo_symbol": "INFY.NS"},
    {"symbol": "TCS", "nse_symbol": "TCS", "company_name": "Tata Consultancy Services Ltd", "aliases": ["tata consultancy"], "yahoo_symbol": "TCS.NS"},
    {"symbol": "RELIANCE", "nse_symbol": "RELIANCE", "company_name": "Reliance Industries Ltd", "aliases": ["ril"], "yahoo_symbol": "RELIANCE.NS"},
    {"symbol": "HDFCBANK", "nse_symbol": "HDFCBANK", "company_name": "HDFC Bank Ltd", "aliases": ["hdfc bank"], "yahoo_symbol": "HDFCBANK.NS"},
    {"symbol": "HINDUNILVR", "nse_symbol": "HINDUNILVR", "company_name": "Hindustan Unilever Ltd", "aliases": ["hul", "hindustan unilever"], "yahoo_symbol": "HINDUNILVR.NS"},
    {"symbol": "ITC", "nse_symbol": "ITC", "company_name": "ITC Ltd", "yahoo_symbol": "ITC.NS"},
    {"symbol": "ADANIENT", "nse_symbol": "ADANIENT", "company_name": "Adani Enterprises Ltd", "yahoo_symbol": "ADANIENT.NS"},
]

_SYMBOL_ALIASES = {
    "HUL": "HINDUNILVR",
}

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _normalize_symbol(symbol: str) -> str:
    raw = (symbol or "").upper().strip().replace(".NS", "").replace(".BO", "")
    return _SYMBOL_ALIASES.get(raw, raw)


def fetch_all_nse_symbols() -> List[Dict[str, Any]]:
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    symbols: List[Dict[str, Any]] = []
    try:
        res = requests.get(url, headers=_HEADERS, timeout=8)
        if res.status_code != 200:
            return symbols
        reader = csv.DictReader(io.StringIO(res.text))
        for row in reader:
            if not isinstance(row, dict):
                continue
            sym = (row.get("SYMBOL") or "").strip()
            if not sym:
                continue
            symbols.append(
                {
                    "symbol": sym,
                    "nse_symbol": sym,
                    "company_name": (row.get("NAME OF COMPANY") or "").strip(),
                    "isin": (row.get(" ISIN NUMBER") or row.get("ISIN NUMBER") or "").strip(),
                    "yahoo_symbol": f"{sym}.NS",
                    "exchange": "NSE",
                }
            )
    except Exception:
        return []
    return symbols


def _bse_rows(payload: Any) -> List[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("Table", "Table1", "data", "Data", "list", "List"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    for value in payload.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return [row for row in value if isinstance(row, dict)]
    return []


def fetch_all_bse_symbols() -> List[Dict[str, Any]]:
    url = "https://api.bseindia.com/BseIndiaAPI/api/ListofScrip/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"
    headers = dict(_HEADERS)
    headers["Referer"] = "https://www.bseindia.com/"
    symbols: List[Dict[str, Any]] = []
    try:
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code != 200:
            return symbols
        for row in _bse_rows(res.json()):
            scrip_cd = str(row.get("SCRIP_CD") or row.get("scrip_cd") or "").strip()
            scrip_id = str(row.get("Scrip_Name") or row.get("SCRIP_ID") or row.get("scrip_id") or "").strip()
            if not scrip_cd:
                continue
            yahoo = f"{scrip_id}.BO" if scrip_id else ""
            symbols.append(
                {
                    "symbol": scrip_id or scrip_cd,
                    "bse_code": scrip_cd,
                    "company_name": str(row.get("Long_Name") or row.get("Scrip_Name") or scrip_id).strip(),
                    "isin": str(row.get("ISIN_NUMBER") or row.get("ISIN") or "").strip(),
                    "yahoo_symbol": yahoo,
                    "exchange": "BSE",
                }
            )
    except Exception:
        return []
    return symbols


class MarketUniverse:
    """Lazy ISIN-merged NSE/BSE map. Empty until first lookup/search."""

    def __init__(self) -> None:
        self.stocks_map: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def ensure(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self.refresh_universe()

    def refresh_universe(self) -> None:
        nse_list = fetch_all_nse_symbols()
        bse_list = fetch_all_bse_symbols()
        isin_map: Dict[str, Dict[str, Any]] = {}
        for stock in nse_list:
            isin = stock.get("isin")
            if isin:
                isin_map[isin] = stock
        for stock in bse_list:
            isin = stock.get("isin")
            if isin in isin_map:
                isin_map[isin]["bse_code"] = stock["bse_code"]
            elif isin:
                isin_map[isin] = stock
        merged = {item["symbol"]: item for item in isin_map.values() if item.get("symbol")}
        if not merged:
            merged = {row["symbol"]: dict(row) for row in _SEARCH_HINTS}
        self.stocks_map = merged

    def get_all(self) -> List[Dict[str, Any]]:
        self.ensure()
        return list(self.stocks_map.values())

    def get_stock_meta(self, symbol: str) -> Optional[Dict[str, Any]]:
        self.ensure()
        sym = _normalize_symbol(symbol)
        if not sym:
            return None
        if sym in self.stocks_map:
            return self.stocks_map[sym]
        for stock in self.stocks_map.values():
            if stock.get("bse_code") == sym or stock.get("nse_symbol") == sym:
                return stock
            aliases = [a.upper() for a in (stock.get("aliases") or [])]
            if sym in aliases:
                return stock
        for hint in _SEARCH_HINTS:
            if hint["symbol"] == sym or sym in [a.upper() for a in hint.get("aliases") or []]:
                return dict(hint)
        if re.fullmatch(r"[A-Z0-9]{2,20}", sym):
            return {
                "symbol": sym,
                "nse_symbol": sym,
                "company_name": sym,
                "yahoo_symbol": f"{sym}.NS",
                "exchange": "NSE",
            }
        return None


universe = MarketUniverse()


def fetch_live_stock_data(meta: Dict[str, Any]) -> Dict[str, Any]:
    stock_data = dict(meta)
    yahoo = meta.get("yahoo_symbol") or f"{meta.get('symbol')}.NS"
    try:
        from marketpulse.pipeline.market_data import fetch_quote

        quote = fetch_quote(yahoo)
        if quote.get("price"):
            stock_data["current_price"] = quote["price"]
            stock_data["quote_source"] = quote.get("source")
    except Exception:
        pass
    try:
        from concurrent.futures import ThreadPoolExecutor

        def _yahoo_overlay() -> Dict[str, Any]:
            import yfinance as yf

            extra: Dict[str, Any] = {}
            ticker = yf.Ticker(yahoo)
            try:
                fast = ticker.fast_info
                last = getattr(fast, "last_price", None) or (fast.get("lastPrice") if hasattr(fast, "get") else None)
                if last:
                    extra["current_price"] = last
                yh = getattr(fast, "year_high", None) or (fast.get("yearHigh") if hasattr(fast, "get") else None)
                yl = getattr(fast, "year_low", None) or (fast.get("yearLow") if hasattr(fast, "get") else None)
                if yh:
                    extra["week52_high"] = yh
                if yl:
                    extra["week52_low"] = yl
            except Exception:
                pass
            try:
                info = ticker.info or {}
            except Exception:
                info = {}
            if info.get("sector"):
                extra["sector"] = info.get("sector")
            if info.get("trailingPE") is not None:
                extra["pe"] = info.get("trailingPE")
                extra["pe_5yr_median"] = info.get("trailingPE")
            if info.get("returnOnEquity") is not None:
                extra["roe"] = round(float(info["returnOnEquity"]) * 100, 2)
            if info.get("returnOnAssets") is not None:
                extra["roce"] = round(float(info["returnOnAssets"]) * 100, 2)
            if info.get("debtToEquity") is not None:
                extra["debt_to_equity"] = round(float(info["debtToEquity"]) / 100, 2)
            if info.get("dividendYield") is not None:
                extra["dividend_yield"] = round(float(info["dividendYield"]) * 100, 2)
            px = info.get("currentPrice") or info.get("regularMarketPrice")
            if px is not None:
                extra["current_price"] = px
            if info.get("fiftyTwoWeekHigh") is not None:
                extra["week52_high"] = info.get("fiftyTwoWeekHigh")
            if info.get("fiftyTwoWeekLow") is not None:
                extra["week52_low"] = info.get("fiftyTwoWeekLow")
            return extra

        with ThreadPoolExecutor(max_workers=1) as pool:
            extra = pool.submit(_yahoo_overlay).result(timeout=6)
            stock_data.update({k: v for k, v in extra.items() if v is not None})
    except Exception:
        pass
    stock_data.setdefault("sector", meta.get("sector") or "Unclassified")
    stock_data.setdefault("promoter_pledge_pct", 0.0)
    return stock_data


def list_stocks() -> List[Dict[str, Any]]:
    return universe.get_all()


def get_stock_meta(symbol: str) -> Optional[Dict[str, Any]]:
    return universe.get_stock_meta(symbol)


def get_stock(symbol: str) -> Optional[Dict[str, Any]]:
    meta = get_stock_meta(symbol)
    if not meta:
        return None
    return fetch_live_stock_data(meta)


class _LazyStockMap:
    def get(self, key, default=None):
        meta = universe.get_stock_meta(key)
        return meta if meta is not None else default


STOCK_BY_SYMBOL = _LazyStockMap()


_FUND_CACHE: tuple[float, Dict[str, Any]] | None = None


def get_fund_underlyings() -> Dict[str, Any]:
    global _FUND_CACHE
    now = time.time()
    if _FUND_CACHE and now - _FUND_CACHE[0] < 3600:
        return _FUND_CACHE[1]
    schemes = {
        "nifty50_index_regular": {"code": "120716", "name": "Nifty 50 Index Fund (Regular)"},
        "nifty50_index_direct": {"code": "120717", "name": "Nifty 50 Index Fund (Direct)"},
        "flexi_cap_regular": {"code": "122639", "name": "Flexi Cap Equity Fund (Regular)"},
        "midcap_150_direct": {"code": "147814", "name": "Nifty Midcap 150 Index Fund (Direct)"},
    }
    default_weights = [
        ("RELIANCE", 8.6),
        ("HDFCBANK", 13.1),
        ("ICICIBANK", 9.2),
        ("INFY", 6.4),
        ("TCS", 4.8),
        ("BHARTIARTL", 4.1),
    ]
    out = {}
    for key, info in schemes.items():
        scheme_name = info["name"]
        try:
            res = requests.get(f"https://api.mfapi.in/mf/{info['code']}", timeout=5)
            if res.status_code == 200:
                payload = res.json()
                data = payload if isinstance(payload, dict) else {}
                scheme_name = (data.get("meta") or {}).get("scheme_name") or scheme_name
        except Exception:
            pass
        out[key] = {"scheme_name": scheme_name, "holdings": list(default_weights)}
    _FUND_CACHE = (now, out)
    return out


def get_filings(symbol: str) -> List[Dict[str, Any]]:
    sym = _normalize_symbol(symbol)
    headers = dict(_HEADERS)
    headers["Accept"] = "*/*"
    filings: List[Dict[str, Any]] = []
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=5)
        res = session.get(
            f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={sym}",
            headers=headers,
            timeout=5,
        )
        if res.status_code != 200:
            return filings
        data = res.json()
        rows = data if isinstance(data, list) else _bse_rows(data)
        for item in rows[:5]:
            dt = item.get("an_dt") or ""
            try:
                filed_at = datetime.strptime(dt, "%d-%b-%Y %H:%M:%S").strftime("%Y-%m-%d")
            except Exception:
                filed_at = str(dt)[:10]
            headline = item.get("desc") or item.get("attchmntText") or ""
            filings.append(
                {
                    "filed_at": filed_at,
                    "headline": headline,
                    "body": item.get("attchmntText") or headline,
                    "summary_3_5yr": f"Exchange filing for {sym}: {headline[:120]}",
                    "source": "NSE",
                }
            )
    except Exception:
        return filings
    return filings


_GSEC_CACHE: tuple[float, float] | None = None


def _gsec_yield() -> float:
    global _GSEC_CACHE
    now = time.time()
    if _GSEC_CACHE and now - _GSEC_CACHE[0] < 300:
        return _GSEC_CACHE[1]
    gsec = 6.92
    try:
        from marketpulse.pipeline.market_data import fetch_quote

        quote = fetch_quote("^TNX")
        if quote.get("price"):
            gsec = round(float(quote["price"]), 2)
    except Exception:
        pass
    if gsec == 6.92:
        try:
            import yfinance as yf

            info = yf.Ticker("^IRX").info or {}
            px = info.get("regularMarketPrice")
            if px:
                gsec = round(float(px), 2)
        except Exception:
            pass
    _GSEC_CACHE = (now, gsec)
    return gsec


def get_fixed_income() -> List[Dict[str, Any]]:
    gsec = _gsec_yield()
    return [
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
            "ytm": round(gsec + 0.35, 2),
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
            "ytm": round(gsec + 0.23, 2),
            "expense_ratio": 0.15,
            "safety_badge": "AAA / State guaranteed pool",
            "tax_rules": "Debt fund taxation: gains added to income as per slab (post Apr 2023 acquisitions).",
            "notes": "Hold to target date to harvest YTM. Avoid trading the NAV.",
        },
        {
            "id": "gsec_10y",
            "name": "10-Year Government of India G-Sec",
            "category": "Sovereign debt",
            "ytm": gsec,
            "expense_ratio": 0.0,
            "safety_badge": "Sovereign",
            "tax_rules": "Interest taxed as income. Listed G-Secs can be held via gilt funds or RBI Retail Direct.",
            "notes": "Benchmark for the secured-debt allocation.",
        },
    ]


def get_secured_bonds() -> List[Dict[str, Any]]:
    gsec = _gsec_yield()
    rows = [
        ("rbi_frb_taxable", "RBI Floating Rate Savings Bonds 2020 (Taxable)", "RBI Bond", 8.05, 7, 1.13, "2020-07-01", "Sovereign", "Rate resets every 6 months. 7-year lock-in."),
        ("goi_gsec_2034", "GOI 7.18% 2034 G-Sec", "Central government", 7.18, 8, 0.0, "2024-07-22", "Sovereign", "Benchmark sovereign via RBI Retail Direct or a gilt fund."),
        ("goi_gsec_2064", "GOI 7.09% 2064 G-Sec", "Central government", 7.09, 38, 0.12, "2024-01-15", "Sovereign", "Ultra-long gilt. Duration risk is high."),
        ("sdl_mh_2034", "Maharashtra SDL 7.32% 2034", "State government", 7.32, 10, 0.30, "2024-03-12", "Sovereign (state)", "Typically 20–40 bps over G-Sec of similar tenor."),
        ("sdl_tn_2033", "Tamil Nadu SDL 7.41% 2033", "State government", 7.41, 9, 0.36, "2024-02-06", "Sovereign (state)", "SDL cash-flows are state-backed."),
        ("sdl_gj_2036", "Gujarat SDL 7.25% 2036", "State government", 7.25, 12, 0.27, "2024-05-21", "Sovereign (state)", "Stronger-state SDL."),
        ("sdl_ka_2032", "Karnataka SDL 7.38% 2032", "State government", 7.38, 8, 0.29, "2024-04-16", "Sovereign (state)", "Use inside the secured-debt bucket."),
        ("nhai_ncd_2029", "NHAI 7.60% Secured NCD 2029", "Corporate (AAA PSU)", 7.60, 5, 0.43, "2024-06-10", "CRISIL AAA / ICRA AAA", "Secured against NHAI assets."),
        ("rec_ncd_2031", "REC 7.72% Secured NCD 2031", "Corporate (AAA PSU)", 7.72, 7, 0.56, "2024-08-19", "CRISIL AAA / CARE AAA", "Power-sector PSU. Treat as AAA corporate, not G-Sec."),
        ("pfc_ncd_2030", "PFC 7.68% Secured NCD 2030", "Corporate (AAA PSU)", 7.68, 6, 0.52, "2024-09-03", "CRISIL AAA / ICRA AAA", "Hold to cash-flow dates."),
        ("irfc_ncd_2032", "IRFC 7.45% Secured NCD 2032", "Corporate (AAA PSU)", 7.45, 8, 0.38, "2024-01-29", "CRISIL AAA", "Railway finance PSU."),
        ("hudco_ncd_2028", "HUDCO 7.55% Secured NCD 2028", "Corporate (AAA PSU)", 7.55, 4, 0.36, "2024-11-12", "ICRA AAA / CARE AAA", "Housing PSU secured paper."),
        ("hdfc_ncd_2029", "HDFC Ltd 7.80% Secured NCD 2029", "Corporate (AAA)", 7.80, 5, 0.60, "2023-12-18", "CRISIL AAA / ICRA AAA", "Housing-finance secured NCD."),
        ("lt_ncd_2030", "L&T 7.70% Secured NCD 2030", "Corporate (AAA)", 7.70, 6, 0.48, "2024-02-28", "CRISIL AAA", "Industrial conglomerate secured NCD."),
        ("bajaj_ncd_2027", "Bajaj Finance 8.05% Secured NCD 2027", "Corporate (AAA)", 8.05, 3, 0.70, "2024-10-07", "CRISIL AAA / ICRA AAA", "NBFC secured NCD."),
    ]
    return [
        {
            "id": row[0],
            "name": row[1],
            "issuer_type": row[2],
            "coupon_pct": row[3],
            "tenure_years": row[4],
            "ytm": round(gsec + row[5], 2),
            "issued_on": row[6],
            "rating": row[7],
            "notes": row[8],
        }
        for row in rows
    ]


def get_sgb_series() -> List[Dict[str, Any]]:
    gold_spot = 7620.0
    try:
        from marketpulse.pipeline.market_data import fetch_quote

        quote = fetch_quote("GOLDBEES.NS")
        if quote.get("price"):
            gold_spot = round(float(quote["price"]) * 100, 2)
    except Exception:
        pass
    try:
        import yfinance as yf

        info = yf.Ticker("GOLDBEES.NS").info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price:
            gold_spot = round(float(price) * 100, 2)
    except Exception:
        pass
    series_data = [
        {"series": "SGBNOV27", "nse_symbol": "SGBNOV27", "maturity": "2027-11-30", "price_offset": 0.95},
        {"series": "SGBDEC28", "nse_symbol": "SGBDEC28", "maturity": "2028-12-17", "price_offset": 0.985},
        {"series": "SGBFEB31", "nse_symbol": "SGBFEB31", "maturity": "2031-02-24", "price_offset": 1.008},
    ]
    out = []
    for sgb in series_data:
        mkt_price = round(gold_spot * sgb["price_offset"], 2)
        disc_pct = round(((gold_spot - mkt_price) / gold_spot) * 100, 2) if gold_spot else 0
        out.append(
            {
                "series": sgb["series"],
                "nse_symbol": sgb["nse_symbol"],
                "market_price": mkt_price,
                "gold_spot_inr": gold_spot,
                "discount_pct": disc_pct,
                "maturity": sgb["maturity"],
            }
        )
    return out


def get_default_valuation() -> Dict[str, Any]:
    nifty_level = 24780.0
    smallcap_level = 16840.0
    pe = 21.8
    yield_val = 1.22
    gsec = _gsec_yield()
    try:
        from marketpulse.pipeline.market_data import fetch_quote

        nifty = fetch_quote("^NSEI")
        if nifty.get("price"):
            nifty_level = nifty["price"]
        small = fetch_quote("^CNXSC")
        if small.get("price"):
            smallcap_level = small["price"]
    except Exception:
        pass
    try:
        import yfinance as yf

        info = yf.Ticker("^NSEI").info or {}
        nifty_level = info.get("currentPrice") or info.get("regularMarketPrice") or nifty_level
        pe = info.get("trailingPE") or pe
        if info.get("dividendYield") is not None:
            yield_val = round(float(info["dividendYield"]) * 100, 2)
    except Exception:
        pass
    return {
        "nifty_pe": pe,
        "nifty_pb": 3.6,
        "dividend_yield": yield_val,
        "market_cap_to_gdp": 1.18,
        "nifty50_level": nifty_level,
        "smallcap250_level": smallcap_level,
        "gsec_10y_yield": gsec,
    }


def get_broker_demo_holdings() -> List[Dict[str, Any]]:
    rows = [
        {"symbol": "HDFCBANK", "company_name": "HDFC Bank Ltd", "asset_type": "equity", "sector": "Banking", "quantity": 40, "avg_price": 1480, "current_price": 1672, "fund_name": None, "isin": "INE040A01034", "purchase_date": "2023-02-11"},
        {"symbol": "TCS", "company_name": "Tata Consultancy Services Ltd", "asset_type": "equity", "sector": "IT", "quantity": 12, "avg_price": 3600, "current_price": 3920, "fund_name": None, "isin": "INE467B01029", "purchase_date": "2022-11-03"},
        {"symbol": "ADANIENT", "company_name": "Adani Enterprises Ltd", "asset_type": "equity", "sector": "Infrastructure", "quantity": 18, "avg_price": 2100, "current_price": 2488, "fund_name": None, "isin": "INE423A01024", "purchase_date": "2024-01-19"},
        {"symbol": "NIFTY50REG", "company_name": "Nifty 50 Index Fund (Regular)", "asset_type": "mutual_fund", "sector": "Index", "quantity": 820, "avg_price": 148, "current_price": 176, "fund_name": "Nifty 50 Index Fund (Regular)", "isin": "INF000NIFTYR", "purchase_date": "2021-08-01"},
        {"symbol": "FLEXIREG", "company_name": "Flexi Cap Equity Fund (Regular)", "asset_type": "mutual_fund", "sector": "Flexi Cap", "quantity": 640, "avg_price": 92, "current_price": 118, "fund_name": "Flexi Cap Equity Fund (Regular)", "isin": "INF000FLEXIR", "purchase_date": "2022-04-15"},
        {"symbol": "GSEC10", "company_name": "10-Year G-Sec allocation", "asset_type": "debt", "sector": "Sovereign", "quantity": 80, "avg_price": 98.4, "current_price": 101.2, "fund_name": None, "isin": "IN002023GSEC", "purchase_date": "2024-06-01"},
    ]
    return [enrich_holding(dict(row)) for row in rows]


def enrich_holding(row: dict) -> dict:
    symbol = (row.get("symbol") or "").upper().strip()
    meta = universe.get_stock_meta(symbol) or {}
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
    rows = universe.get_all() + _SEARCH_HINTS
    seen = set()
    unique = []
    for row in rows:
        key = (row.get("symbol") or "").upper()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(row)
    if not q:
        return unique[:limit]
    tokens = [t for t in re.split(r"[\s,]+", q) if t]
    scored = []
    for row in unique:
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


def filings_for(symbol: str) -> list:
    return get_filings(symbol)


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
        return [("roe", "ROE", "%"), ("dividend_yield", "Dividend yield", "%")]
    return [
        ("roe", "ROE", "%"),
        ("roce", "ROCE", "%"),
        ("fcf_crore", "FCF (₹ cr)", ""),
        ("dividend_yield", "Dividend yield", "%"),
    ]


def sector_metric_deltas(stock: dict) -> list:
    sector = stock.get("sector") or ""
    out = []
    for key, label, unit in _sector_metric_keys(sector):
        value = stock.get(key)
        out.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "value": value,
                "sector_median": None,
                "delta_pct": None,
                "direction": "flat",
            }
        )
    return out


def __getattr__(name: str):
    """Lazy module aliases so older `from catalog import STOCKS` still works."""
    mapping = {
        "STOCKS": list_stocks,
        "FIXED_INCOME": get_fixed_income,
        "SECURED_BONDS": get_secured_bonds,
        "SGB_SERIES": get_sgb_series,
        "DEFAULT_VALUATION": get_default_valuation,
        "FUND_UNDERLYINGS": get_fund_underlyings,
        "BROKER_DEMO_HOLDINGS": get_broker_demo_holdings,
    }
    if name in mapping:
        return mapping[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
