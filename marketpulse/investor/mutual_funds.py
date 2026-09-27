"""Live Indian mutual-fund directory (mfapi.in / AMFI), grouped for the Funds hub.

List and NAV history are fetched on first use and cached. Nothing runs at import.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

MFAPI_LIST = "https://api.mfapi.in/mf"
MFAPI_SCHEME = "https://api.mfapi.in/mf/{code}"
_HEADERS = {"User-Agent": "MarketPulseIndia/1.0 (educational)"}

CATEGORIES = [
    {"id": "equity", "label": "Equity"},
    {"id": "debt", "label": "Debt"},
    {"id": "hybrid", "label": "Hybrid"},
    {"id": "solution", "label": "Solution oriented"},
    {"id": "other", "label": "Other"},
]

_LIST_CACHE: tuple[float, List[Dict[str, Any]]] | None = None
_DETAIL_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_BOARD_CACHE: tuple[float, Dict[str, Any]] | None = None
_LIST_TTL = 12 * 3600
_DETAIL_TTL = 6 * 3600
_BOARD_TTL = 6 * 3600

_PREFERRED_AMCS = (
    "sbi ",
    "hdfc ",
    "icici ",
    "nippon",
    "uti ",
    "axis ",
    "kotak",
    "mirae",
    "parag parikh",
    "quant ",
    "dsp ",
    "tata ",
    "motilal",
    "edelweiss",
    "bandhan",
    "aditya birla",
)


def classify_scheme(name: str, scheme_category: str = "") -> Tuple[str, str]:
    """Return (category_id, sector_label) from scheme name / AMFI category."""
    n = f"{name or ''} {scheme_category or ''}".lower()

    if any(k in n for k in ("retirement", "children", "childrens", "pension", "solution")):
        category = "solution"
    elif any(
        k in n
        for k in (
            "arbitrage",
            "balanced advantage",
            "dynamic asset",
            "aggressive hybrid",
            "conservative hybrid",
            "equity savings",
            "multi asset",
            "hybrid",
        )
    ):
        category = "hybrid"
    elif any(k in n for k in ("gold", "silver etf", "silver fund", "commodity")):
        category = "other"
    elif any(
        k in n
        for k in (
            "gilt",
            "liquid",
            "overnight",
            "money market",
            "corporate bond",
            "credit risk",
            "banking and psu",
            "banking & psu",
            "short duration",
            "medium duration",
            "medium to long",
            "long duration",
            "dynamic bond",
            "floater",
            "ultra short",
            "low duration",
            "debt fund",
            "income fund",
            "gilt fund",
            "fixed maturity",
        )
    ):
        category = "debt"
    else:
        category = "equity"

    sector_rules = [
        ("Banking & financials", ("banking and financial", "banking & financial", "financial services", "banking fund")),
        ("IT", ("technology", "digital", " infotech", "information tech")),
        ("Pharma & healthcare", ("pharma", "healthcare", "health care")),
        ("FMCG & consumption", ("fmcg", "consumption", "consumer")),
        ("Infrastructure", ("infra", "infrastructure")),
        ("PSU", ("psu",)),
        ("Energy & power", ("energy", "power fund")),
        ("Auto", ("auto fund", "automobile")),
        ("ELSS / tax saver", ("elss", "tax saver", "taxsaver")),
        ("Index / ETF", ("index", "nifty", "sensex", " etf", "exchange traded")),
        ("International", ("us equity", "nasdaq", "international", "global", "hang seng")),
        ("Small cap", ("small cap", "smallcap")),
        ("Mid cap", ("mid cap", "midcap")),
        ("Large cap", ("large cap", "largecap", "bluechip", "blue chip")),
        ("Flexi / multi cap", ("flexi cap", "flexicap", "multi cap", "multicap", "focused")),
        ("Gold / commodity", ("gold", "silver", "commodity")),
        ("Overnight", ("overnight",)),
        ("Liquid", ("liquid",)),
        ("Gilt", ("gilt",)),
        ("Corporate bond", ("corporate bond",)),
        ("Credit risk", ("credit risk",)),
        ("Arbitrage", ("arbitrage",)),
        ("Balanced advantage", ("balanced advantage", "dynamic asset")),
        ("Aggressive hybrid", ("aggressive hybrid",)),
        ("Conservative hybrid", ("conservative hybrid",)),
        ("Retirement / children", ("retirement", "children", "pension")),
    ]
    for label, keys in sector_rules:
        if any(k in n for k in keys):
            return category, label
    if category == "debt":
        return category, "Income / duration"
    if category == "hybrid":
        return category, "Hybrid"
    if category == "solution":
        return category, "Solution oriented"
    if category == "other":
        return category, "Other"
    return category, "Diversified equity"


def _is_direct_growth(name: str, plan: str = "", option: str = "") -> bool:
    blob = f"{name or ''} {plan or ''} {option or ''}".lower()
    return "direct" in blob and "growth" in blob and "idcw" not in blob


def _is_growth(name: str, plan: str = "", option: str = "") -> bool:
    blob = f"{name or ''} {plan or ''} {option or ''}".lower()
    return "growth" in blob and "idcw" not in blob


def _is_index_scheme(row: Dict[str, Any]) -> bool:
    hay = " ".join(
        [
            str(row.get("scheme_name") or ""),
            str(row.get("scheme_category") or ""),
            str(row.get("sector") or ""),
        ]
    ).lower()
    return any(k in hay for k in ("index", "etf", "nifty", "sensex", "exchange traded", "bees"))


def _amc_rank(name: str) -> int:
    n = (name or "").lower()
    for i, amc in enumerate(_PREFERRED_AMCS):
        if amc in n:
            return i
    return 80


def _parse_amfi_navall() -> List[Dict[str, Any]]:
    text = ""
    for url in (
        "https://www.amfiindia.com/spages/NAVAll.txt",
        "https://portal.amfiindia.com/spages/NAVAll.txt",
    ):
        try:
            res = requests.get(url, headers=_HEADERS, timeout=15)
            if res.status_code == 200 and ";" in (res.text or ""):
                text = res.text
                break
        except Exception:
            continue
    if not text:
        return []
    rows: List[Dict[str, Any]] = []
    section = ""
    house = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("scheme code"):
            continue
        if ";" not in line:
            if line.lower().startswith("open ended") or line.lower().startswith("close ended") or line.lower().startswith("interval"):
                inner = line
                if "(" in line and line.endswith(")"):
                    inner = line[line.find("(") + 1 : -1]
                section = inner
            elif "mutual fund" in line.lower():
                house = line
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        if len(parts) >= 8:
            code, isin_g, _isin_d, short_name, plan, option, nav_s, nav_date = parts[:8]
        else:
            code, isin_g, _isin_d, short_name, nav_s, nav_date = parts[:6]
            plan, option = "", ""
        try:
            nav = float(nav_s) if nav_s not in {"", "N.A.", "NA", "-"} else None
        except ValueError:
            nav = None
        display = " - ".join(p for p in (short_name, plan, option) if p)
        category, sector = classify_scheme(display, section)
        rows.append(
            {
                "scheme_code": code,
                "scheme_name": display,
                "short_name": short_name,
                "plan": plan,
                "option": option,
                "isin": isin_g if isin_g not in {"", "-"} else "",
                "fund_house": house,
                "scheme_category": section,
                "category": category,
                "sector": sector,
                "nav": nav,
                "nav_date": nav_date,
                "direct_growth": _is_direct_growth(short_name, plan, option),
            }
        )
    return rows


def _parse_mfapi_list() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        res = requests.get(MFAPI_LIST, headers=_HEADERS, timeout=12)
        if res.status_code != 200:
            return rows
        payload = res.json()
        if not isinstance(payload, list):
            return rows
        for item in payload:
            if not isinstance(item, dict):
                continue
            code = str(item.get("schemeCode") or item.get("scheme_code") or "").strip()
            name = str(item.get("schemeName") or item.get("scheme_name") or "").strip()
            if not code or not name:
                continue
            category, sector = classify_scheme(name)
            rows.append(
                {
                    "scheme_code": code,
                    "scheme_name": name,
                    "short_name": name,
                    "plan": "",
                    "option": "",
                    "isin": "",
                    "fund_house": "",
                    "scheme_category": "",
                    "category": category,
                    "sector": sector,
                    "nav": None,
                    "nav_date": "",
                    "direct_growth": _is_direct_growth(name),
                }
            )
    except Exception:
        return []
    return rows


def fetch_scheme_list() -> List[Dict[str, Any]]:
    global _LIST_CACHE
    now = time.time()
    if _LIST_CACHE and now - _LIST_CACHE[0] < _LIST_TTL:
        return _LIST_CACHE[1]
    rows = _parse_amfi_navall() or _parse_mfapi_list()
    if rows:
        _LIST_CACHE = (now, rows)
    return rows or (_LIST_CACHE[1] if _LIST_CACHE else [])


def _parse_nav_date(value: str) -> Optional[datetime]:
    for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime((value or "").strip(), fmt)
        except ValueError:
            continue
    return None


def _period_return(history: List[dict], days: int) -> Optional[float]:
    points = []
    for row in history:
        if not isinstance(row, dict):
            continue
        dt = _parse_nav_date(str(row.get("date") or ""))
        try:
            nav = float(row.get("nav") or 0)
        except (TypeError, ValueError):
            nav = 0.0
        if dt and nav > 0:
            points.append((dt, nav))
    if len(points) < 2:
        return None
    points.sort(key=lambda p: p[0])
    latest_dt, latest_nav = points[-1]
    target = latest_dt - timedelta(days=days)
    older = [p for p in points if p[0] <= target]
    if not older:
        return None
    base_nav = older[-1][1]
    if base_nav <= 0:
        return None
    return round(((latest_nav / base_nav) - 1) * 100, 2)


def fetch_scheme_detail(code: str) -> Optional[Dict[str, Any]]:
    code = str(code or "").strip()
    if not code:
        return None
    now = time.time()
    cached = _DETAIL_CACHE.get(code)
    if cached and now - cached[0] < _DETAIL_TTL:
        return dict(cached[1])
    try:
        res = requests.get(MFAPI_SCHEME.format(code=code), headers=_HEADERS, timeout=8)
        if res.status_code != 200:
            return None
        payload = res.json()
        if not isinstance(payload, dict):
            return None
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        history = payload.get("data") if isinstance(payload.get("data"), list) else []
        name = meta.get("scheme_name") or ""
        amfi_cat = meta.get("scheme_category") or ""
        category, sector = classify_scheme(name, amfi_cat)
        latest = history[0] if history and isinstance(history[0], dict) else {}
        try:
            nav = float(latest.get("nav") or 0) or None
        except (TypeError, ValueError):
            nav = None
        detail = {
            "scheme_code": str(meta.get("scheme_code") or code),
            "scheme_name": name or f"Scheme {code}",
            "fund_house": meta.get("fund_house") or "",
            "scheme_type": meta.get("scheme_type") or "",
            "scheme_category": amfi_cat,
            "category": category,
            "sector": sector,
            "nav": nav,
            "nav_date": latest.get("date") or "",
            "return_1m": _period_return(history, 30),
            "return_1y": _period_return(history, 365),
            "return_3y": _period_return(history, 1095),
        }
        _DETAIL_CACHE[code] = (now, detail)
        return dict(detail)
    except Exception:
        return None


def search_funds(
    query: str,
    limit: int = 80,
    category: str = "",
    index_only: bool = False,
) -> List[Dict[str, Any]]:
    q = (query or "").strip().lower()
    cat = (category or "").strip().lower()
    rows = fetch_scheme_list()
    if index_only:
        rows = [r for r in rows if _is_index_scheme(r)]
    if cat and cat not in {"", "all"}:
        rows = [r for r in rows if r.get("category") == cat]
    if not q:
        preferred = [r for r in rows if r.get("direct_growth")]
        pool = preferred or rows
        pool = sorted(pool, key=lambda r: (_amc_rank(r["scheme_name"]), r["scheme_name"]))
        return pool[:limit]
    tokens = [t for t in re.split(r"[\s,]+", q) if t]
    scored = []
    for row in rows:
        hay = " ".join(
            [
                str(row.get("scheme_name") or ""),
                str(row.get("short_name") or ""),
                str(row.get("scheme_code") or ""),
                str(row.get("isin") or ""),
                str(row.get("sector") or ""),
                str(row.get("fund_house") or ""),
                str(row.get("scheme_category") or ""),
            ]
        ).lower()
        if q in hay or all(t in hay for t in tokens):
            name = (row.get("scheme_name") or "").lower()
            exact = 0 if q == (row.get("scheme_code") or "").lower() else 1
            prefix = 0 if name.startswith(q) or (row.get("short_name") or "").lower().startswith(q) else 1
            growth = 0 if row.get("direct_growth") else 1
            scored.append((exact, growth, prefix, len(name), row))
    scored.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return [item[4] for item in scored[:limit]]


def get_fund(code: str) -> Optional[Dict[str, Any]]:
    code = str(code or "").strip()
    listed = None
    for row in fetch_scheme_list():
        if row.get("scheme_code") == code:
            listed = dict(row)
            break
    detail = fetch_scheme_detail(code)
    if listed and detail:
        merged = dict(listed)
        for key, value in detail.items():
            if value not in (None, "", []):
                merged[key] = value
        return merged
    return detail or listed


def _pick_candidates(rows: List[Dict[str, Any]], key: str, value: str, cap: int = 6) -> List[Dict[str, Any]]:
    matched = [r for r in rows if r.get(key) == value]
    growth = [r for r in matched if r.get("direct_growth")]
    if len(growth) < 4:
        extra = [
            r
            for r in matched
            if _is_growth(r.get("scheme_name") or "", r.get("plan") or "", r.get("option") or "") and r not in growth
        ]
        growth = growth + extra
    growth.sort(key=lambda r: (_amc_rank(r["scheme_name"]), len(r["scheme_name"])))
    return growth[:cap]


def _enrich_many(rows: List[Dict[str, Any]], budget_s: float = 6.0) -> List[Dict[str, Any]]:
    """Attach 1Y/3Y returns when mfapi answers quickly; always keep AMFI rows."""
    by_code = {str(r["scheme_code"]): dict(r) for r in rows}
    deadline = time.time() + budget_s
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(fetch_scheme_detail, code): code for code in by_code}
        for fut in as_completed(futs):
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                detail = fut.result(timeout=min(2.5, remaining))
            except Exception:
                detail = None
            if not detail:
                continue
            code = str(detail.get("scheme_code") or futs[fut])
            merged = by_code.get(code) or {}
            merged.update({k: v for k, v in detail.items() if v not in (None, "", [])})
            by_code[code] = merged
    return [by_code[r["scheme_code"]] for r in rows]


def _top(rows: List[Dict[str, Any]], n: int = 4) -> List[Dict[str, Any]]:
    def score(item: Dict[str, Any]) -> float:
        r = item.get("return_1y")
        return float(r) if r is not None else -9999.0

    ranked = sorted(rows, key=score, reverse=True)
    return ranked[:n]


def funds_board() -> Dict[str, Any]:
    """Category counts plus 1Y leaders by category and by equity sector."""
    global _BOARD_CACHE
    now = time.time()
    if _BOARD_CACHE and now - _BOARD_CACHE[0] < _BOARD_TTL:
        return dict(_BOARD_CACHE[1])
    rows = fetch_scheme_list()
    counts = {c["id"]: 0 for c in CATEGORIES}
    for row in rows:
        cat = row.get("category") or "other"
        if cat in counts:
            counts[cat] += 1
        else:
            counts["other"] += 1
    categories = [{**c, "count": counts.get(c["id"], 0)} for c in CATEGORIES]

    candidates: List[Dict[str, Any]] = []
    seen = set()
    for cat in ("equity", "debt", "hybrid", "solution", "other"):
        for row in _pick_candidates(rows, "category", cat, cap=6):
            if row["scheme_code"] not in seen:
                seen.add(row["scheme_code"])
                candidates.append(row)
    equity_sectors = [
        "Large cap",
        "Mid cap",
        "Small cap",
        "Flexi / multi cap",
        "ELSS / tax saver",
        "Index / ETF",
        "Banking & financials",
        "IT",
        "Pharma & healthcare",
        "Infrastructure",
    ]
    for sector in equity_sectors:
        for row in _pick_candidates(rows, "sector", sector, cap=4):
            if row["scheme_code"] not in seen:
                seen.add(row["scheme_code"])
                candidates.append(row)

    enriched = _enrich_many(candidates, budget_s=6.0) if candidates else []
    top_by_category = {}
    for cat in ("equity", "debt", "hybrid", "solution", "other"):
        pool = [r for r in enriched if r.get("category") == cat] or _pick_candidates(rows, "category", cat, cap=4)
        top_by_category[cat] = _top(pool, n=4) if any(r.get("return_1y") is not None for r in pool) else pool[:4]
    top_by_sector = {}
    for sector in equity_sectors:
        pool = [r for r in enriched if r.get("sector") == sector] or _pick_candidates(rows, "sector", sector, cap=3)
        if not pool:
            continue
        top_by_sector[sector] = _top(pool, n=3) if any(r.get("return_1y") is not None for r in pool) else pool[:3]

    board = {
        "categories": categories,
        "top_by_category": top_by_category,
        "top_by_sector": top_by_sector,
        "source": "amfiindia.com",
        "scheme_count": len(rows),
        "note": "Latest NAVs from AMFI. 1-year returns are shown when history loads in time. Educational ranking, not a recommendation.",
    }
    if rows:
        _BOARD_CACHE = (now, board)
    return dict(board)
