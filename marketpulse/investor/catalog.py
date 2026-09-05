import csv
import io
from typing import Any, Dict, List, Optional
import requests
import yfinance as yf


# ---------------------------------------------------------------------------
# Dynamic Symbol Master Fetchers
# ---------------------------------------------------------------------------

def fetch_all_nse_symbols() -> List[Dict[str, Any]]:
    """Fetches the complete official equity symbol list directly from NSE."""
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    symbols = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            reader = csv.DictReader(io.StringIO(res.text))
            for row in reader:
                sym = row.get("SYMBOL", "").strip()
                if sym:
                    symbols.append({
                        "symbol": sym,
                        "nse_symbol": sym,
                        "company_name": row.get("NAME OF COMPANY", "").strip(),
                        "isin": row.get(" ISIN NUMBER", "").strip(),
                        "yahoo_symbol": f"{sym}.NS",
                        "exchange": "NSE",
                    })
    except Exception as e:
        print(f"Error fetching NSE symbols: {e}")

    return symbols


def fetch_all_bse_symbols() -> List[Dict[str, Any]]:
    """Fetches active equity scrip codes and details directly from BSE."""
    url = "https://api.bseindia.com/BseIndiaAPI/api/ListofScrip/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bseindia.com/",
    }

    symbols = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for row in data:
                scrip_cd = str(row.get("SCRIP_CD", "")).strip()
                scrip_id = row.get("Scrip_Name", "").strip()
                if scrip_cd:
                    symbols.append({
                        "symbol": scrip_id,
                        "bse_code": scrip_cd,
                        "company_name": row.get("Long_Name", "").strip(),
                        "isin": row.get("ISIN_NUMBER", "").strip(),
                        "yahoo_symbol": f"{scrip_id}.BO",
                        "exchange": "BSE",
                    })
    except Exception as e:
        print(f"Error fetching BSE symbols: {e}")

    return symbols


class MarketUniverse:
    """Manages full market coverage with unified ISIN-based mapping."""

    def __init__(self):
        self.stocks_map: Dict[str, Dict[str, Any]] = {}
        self.refresh_universe()

    def refresh_universe(self):
        nse_list = fetch_all_nse_symbols()
        bse_list = fetch_all_bse_symbols()

        # Group by ISIN to map NSE and BSE codes to the same company
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

        self.stocks_map = {
            item["symbol"]: item for item in isin_map.values()
        }

    def get_all(self) -> List[Dict[str, Any]]:
        return list(self.stocks_map.values())

    def get_stock(self, symbol: str) -> Optional[Dict[str, Any]]:
        sym = symbol.upper().strip().replace(".NS", "").replace(".BO", "")

        if sym in self.stocks_map:
            return self.stocks_map[sym]

        # Fallback search by BSE scrip code or secondary symbol
        for stock in self.stocks_map.values():
            if stock.get("bse_code") == sym or stock.get("nse_symbol") == sym:
                return stock

        return None


# Global market instance
universe = MarketUniverse()


# ---------------------------------------------------------------------------
# Dynamic Fetcher Function Updates
# ---------------------------------------------------------------------------

def fetch_live_stock_data(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Fetches live market metrics via Yahoo Finance using dynamically mapped symbols."""
    ticker_symbol = meta.get("yahoo_symbol") or f"{meta['symbol']}.NS"
    ticker = yf.Ticker(ticker_symbol)

    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    stock_data = dict(meta)
    stock_data.update({
        "pe": info.get("trailingPE"),
        "roe": round((info.get("returnOnEquity") or 0) * 100, 2),
        "debt_to_equity": round((info.get("debtToEquity") or 0) / 100, 2),
        "dividend_yield": round((info.get("dividendYield") or 0) * 100, 2),
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "week52_high": info.get("fiftyTwoWeekHigh"),
        "week52_low": info.get("fiftyTwoWeekLow"),
    })
    return stock_data


def get_stock(symbol: str) -> Optional[Dict[str, Any]]:
    meta = universe.get_stock(symbol)
    if meta:
        return fetch_live_stock_data(meta)
    return None