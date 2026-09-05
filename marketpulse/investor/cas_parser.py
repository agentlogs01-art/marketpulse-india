"""Parse CAS CSV/Excel/text/JSON (and lightly scraped PDF bytes) into holdings."""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Optional

from marketpulse.investor.catalog import BROKER_DEMO_HOLDINGS, enrich_holding


HEADER_ALIASES = {
    "symbol": {"symbol", "ticker", "scrip", "nse", "nse_symbol"},
    "company_name": {"company", "company_name", "name", "scrip_name"},
    "isin": {"isin"},
    "quantity": {"qty", "quantity", "units", "holding"},
    "avg_price": {"avg", "avg_price", "average_cost", "buy_price", "cost"},
    "current_price": {"ltp", "price", "current_price", "nav", "close"},
    "asset_type": {"type", "asset_type", "asset"},
    "sector": {"sector"},
    "fund_name": {"scheme", "fund", "fund_name", "scheme_name"},
    "purchase_date": {"date", "purchase_date", "buy_date"},
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def _map_header(name: str) -> Optional[str]:
    key = _norm(name)
    for field, aliases in HEADER_ALIASES.items():
        if key in aliases:
            return field
    return None


def _to_float(value) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("₹", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _asset_type(value: str, fund_name: Optional[str]) -> str:
    v = (value or "").lower()
    if fund_name or "fund" in v or "scheme" in v:
        return "mutual_fund"
    if "debt" in v or "bond" in v or "g-sec" in v or "gsec" in v:
        return "debt"
    if "gold" in v or "sgb" in v:
        return "gold"
    if v in {"equity", "mutual_fund", "debt", "gold", "other"}:
        return v
    return "equity"


def parse_holdings_payload(raw: bytes, filename: str = "", broker_token: str = "") -> dict:
    """
    Returns {source, holdings, filename}.
    A broker/Account Aggregator token (any non-empty string in MVP) loads
    the educational demo book used for advisory screens.
    """
    if (broker_token or "").strip():
        holdings = [enrich_holding(dict(h)) for h in BROKER_DEMO_HOLDINGS]
        return {"source": "broker_aa", "filename": filename or "account-aggregator", "holdings": holdings}

    name = (filename or "upload").lower()
    text = ""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="ignore")

    if name.endswith(".json") or text.lstrip().startswith("{") or text.lstrip().startswith("["):
        holdings = _from_json(text)
        source = "manual"
    elif name.endswith((".csv", ".tsv", ".txt", ".xlsx", ".xls")) or "," in text or "\t" in text:
        holdings = _from_tabular(text)
        source = "cas_excel" if name.endswith((".xlsx", ".xls", ".csv", ".tsv")) else "cas_excel"
    else:
        holdings = _from_pdf_like(raw, text)
        source = "cas_pdf"

    if not holdings:
        raise ValueError(
            "Could not find holdings. Upload a CSV with columns symbol, quantity, avg_price "
            "(optional current_price, sector, fund_name) or connect via Account Aggregator."
        )
    return {"source": source, "filename": filename, "holdings": [enrich_holding(h) for h in holdings]}


def _from_json(text: str) -> list:
    data = json.loads(text)
    rows = data.get("holdings") if isinstance(data, dict) else data
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        mapped = {}
        for k, v in row.items():
            field = _map_header(str(k)) or (k if k in HEADER_ALIASES else None)
            if field:
                mapped[field] = v
        if mapped.get("symbol") or mapped.get("fund_name"):
            mapped["quantity"] = _to_float(mapped.get("quantity"))
            mapped["avg_price"] = _to_float(mapped.get("avg_price"))
            mapped["current_price"] = _to_float(mapped.get("current_price"))
            mapped["asset_type"] = _asset_type(str(mapped.get("asset_type") or ""), mapped.get("fund_name"))
            out.append(mapped)
    return out


def _from_tabular(text: str) -> list:
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|") if sample.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    out = []
    for row in reader:
        mapped = {}
        for k, v in row.items():
            field = _map_header(k or "")
            if field:
                mapped[field] = v
        if not (mapped.get("symbol") or mapped.get("fund_name") or mapped.get("company_name")):
            continue
        mapped["symbol"] = (mapped.get("symbol") or mapped.get("fund_name") or mapped.get("company_name") or "").upper()
        mapped["quantity"] = _to_float(mapped.get("quantity"))
        mapped["avg_price"] = _to_float(mapped.get("avg_price"))
        mapped["current_price"] = _to_float(mapped.get("current_price"))
        mapped["asset_type"] = _asset_type(str(mapped.get("asset_type") or ""), mapped.get("fund_name"))
        out.append(mapped)
    return out


_LINE_RE = re.compile(
    r"(?P<symbol>[A-Z]{2,}[A-Z0-9]*)[,\s|]+(?P<qty>[\d,.]+)[,\s|]+(?P<avg>[\d,.]+)"
)


def _from_pdf_like(raw: bytes, text: str) -> list:
    extracted = text
    if b"%PDF" in raw[:8]:
        extracted = "".join(chr(b) if 32 <= b < 127 else " " for b in raw)
        extracted = re.sub(r" +", " ", extracted)
    out = []
    for match in _LINE_RE.finditer(extracted.upper()):
        out.append(
            {
                "symbol": match.group("symbol"),
                "quantity": _to_float(match.group("qty")),
                "avg_price": _to_float(match.group("avg")),
                "asset_type": "equity",
            }
        )
    return out
