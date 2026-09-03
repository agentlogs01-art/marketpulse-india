"""
pipeline/ingestion.py

FR-01.2 — News/event ingestion and normalization.

Pulls from free RSS feeds and normalizes every item into the NewsEvent
schema. Published timestamps from the feed drive the overnight lookback
window (ingestion_timestamp is always "now" and must not be used for that
filter). A ranked subset of those events is what the LLM actually sees.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from time import struct_time
from typing import Optional

from marketpulse.models.schemas import EventType, GeographicOrigin, NewsEvent
from marketpulse.utils.timeutils import IST, now_ist

import sys

# Cap how many stories hit Gemini so NSE corporate spam cannot drown the
# overnight macro tape — and so a failed ranking still leaves a digest.
MAX_EVENTS_FOR_LLM = 12

RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 MarketPulseIndia/1.7"
    ),
    "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Curated RSS sources (FR-01.2). Each entry carries a static credibility
# score and a default geographic_origin used when classification
# heuristics below don't find a stronger signal.
RSS_SOURCES = [
    {
        "name": "NSE Corporate Announcements",
        "url": "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",
        "credibility_score": 1.00,
        "default_origin": GeographicOrigin.INDIA,
    },
    {
        "name": "NSE Corporate Actions",
        "url": "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",
        "credibility_score": 1.00,
        "default_origin": GeographicOrigin.INDIA,
    },
    {
        "name": "NSE Financial Results",
        "url": "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml",
        "credibility_score": 1.00,
        "default_origin": GeographicOrigin.INDIA,
    },
    {
        "name": "RBI Press Releases",
        "url": "https://www.rbi.org.in/pressreleases_rss.xml",
        "credibility_score": 0.99,
        "default_origin": GeographicOrigin.INDIA,
    },
    {
        "name": "Economic Times Markets",
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "credibility_score": 0.85,
        "default_origin": GeographicOrigin.INDIA,
    },
    {
        "name": "Moneycontrol Markets",
        "url": "https://www.moneycontrol.com/rss/marketreports.xml",
        "credibility_score": 0.80,
        "default_origin": GeographicOrigin.INDIA,
    },
    {
        "name": "Reuters Business",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "credibility_score": 0.95,
        "default_origin": GeographicOrigin.GLOBAL,
    },
    {
        "name": "MarketWatch Top Stories",
        "url": "https://www.marketwatch.com/rss/topstories",
        "credibility_score": 0.90,
        "default_origin": GeographicOrigin.GLOBAL,
    },
    {
        "name": "Investing.com Commodities",
        "url": "https://www.investing.com/rss/news_11.rss",
        "credibility_score": 0.88,
        "default_origin": GeographicOrigin.GLOBAL,
    },
    {
        "name": "BBC Business",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "credibility_score": 0.92,
        "default_origin": GeographicOrigin.GLOBAL,
    },
    {
        "name": "US Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "credibility_score": 0.99,
        "default_origin": GeographicOrigin.US,
    },
]

_EVENT_TYPE_KEYWORDS: dict[EventType, list[str]] = {
    EventType.CENTRAL_BANK: ["fed", "fomc", "federal reserve", "rate decision", "powell"],
    EventType.INDIA_DOMESTIC: ["rbi", "sebi", "repo rate", "monetary policy committee", "mpc", "gst council", "union budget"],
    EventType.COMMODITY: ["crude", "brent", "oil price", "gold price", "opec"],
    EventType.GEOPOLITICAL: ["war", "sanctions", "conflict", "tension", "ceasefire"],
    EventType.CURRENCY: ["rupee", "dollar index", "forex", "inr/usd"],
    EventType.MACRO_DATA: ["gdp", "inflation", "cpi", "pmi data", "jobs report", "nonfarm"],
    EventType.REGULATORY: ["regulation", "compliance", "tariff", "ban on"],
    EventType.EARNINGS: ["quarterly results", "earnings", "q1 results", "q2 results", "q3 results", "q4 results"],
}

_TYPE_PRIORITY = {
    EventType.CENTRAL_BANK: 8,
    EventType.INDIA_DOMESTIC: 8,
    EventType.MACRO_DATA: 7,
    EventType.GEOPOLITICAL: 6,
    EventType.COMMODITY: 6,
    EventType.CURRENCY: 5,
    EventType.REGULATORY: 5,
    EventType.EARNINGS: 4,
    EventType.OTHER: 1,
}


def classify_event_type(headline: str, body: str) -> EventType:
    text = f"{headline} {body}".lower()
    for event_type, keywords in _EVENT_TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return event_type
    return EventType.OTHER


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _entry_get(entry, key: str, default: str = "") -> str:
    if hasattr(entry, key):
        value = getattr(entry, key)
        if value:
            return str(value)
    if isinstance(entry, dict):
        return str(entry.get(key, default) or default)
    return default


def published_at_from_entry(entry) -> Optional[str]:
    """ISO-8601 UTC from feedparser published_parsed / updated_parsed."""
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if isinstance(entry, dict) and parsed is None:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if isinstance(parsed, struct_time):
        try:
            dt = datetime(*parsed[:6], tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            return None
    return None


def overnight_lookback_hours(now: Optional[datetime] = None) -> int:
    """
    Hours back from now to the previous NSE session close (15:30 IST),
    plus a 2h buffer. Monday (and other days after a weekend) therefore
    keep Friday afternoon / weekend wires instead of a flat 16h window
    that would drop them all.
    """
    ist = now or now_ist()
    if ist.tzinfo is None:
        ist = ist.replace(tzinfo=IST)
    else:
        ist = ist.astimezone(IST)
    weekday = ist.weekday()  # Mon=0
    days_back = 3 if weekday == 0 else 1
    prev_close = datetime(ist.year, ist.month, ist.day, 15, 30, tzinfo=IST) - timedelta(days=days_back)
    hours = (ist - prev_close).total_seconds() / 3600.0 + 2.0
    return max(16, int(hours) + 1)


def fetch_raw_feed_items(source: dict) -> list:
    """
    Fetch and parse a single RSS source. Returns a list of raw entries.
    Isolated so tests can mock without hitting the network.
    """
    import feedparser
    import socket
    import requests
    import urllib3

    original_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(10.0)

    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.get(
            source["url"],
            headers=RSS_HEADERS,
            verify=False,
            timeout=10,
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        return list(parsed.entries)
    except requests.exceptions.RequestException as req_err:
        print(
            f"[ingestion] {source['name']}: network/HTTP error: {req_err}",
            file=sys.stderr,
        )
        return []
    except Exception as exc:
        print(f"[ingestion] {source['name']}: parse error: {exc}", file=sys.stderr)
        return []
    finally:
        socket.setdefaulttimeout(original_timeout)


def normalize_entry(entry, source: dict) -> NewsEvent:
    headline = _strip_html(_entry_get(entry, "title"))
    summary = _strip_html(_entry_get(entry, "summary") or _entry_get(entry, "description"))
    link = _entry_get(entry, "link")
    published_at = published_at_from_entry(entry)

    event_type = classify_event_type(headline, summary)
    origin = source["default_origin"]
    if event_type == EventType.INDIA_DOMESTIC:
        origin = GeographicOrigin.INDIA

    return NewsEvent(
        source=source["name"],
        source_url=link,
        headline=headline,
        body_summary=summary,
        raw_body=summary,
        event_type=event_type,
        geographic_origin=origin,
        credibility_score=source["credibility_score"],
        is_scheduled_event=False,
        published_at=published_at,
    )


def _parse_event_time(event: NewsEvent) -> Optional[datetime]:
    raw = event.published_at or event.ingestion_timestamp
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_within_lookback_window(event: NewsEvent, lookback_hours: int = 16) -> bool:
    """
    FR-01.2: keep items published within the lookback window. Missing
    timestamps fail open so a feed without dates is not silently dropped.
    """
    ts = _parse_event_time(event)
    if ts is None:
        return True
    if event.published_at is None:
        # ingestion_timestamp is "now" — not a publish time. Keep the item
        # and let ranking decide; a naive cutoff here would be a no-op.
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= cutoff


def _event_rank(event: NewsEvent) -> tuple:
    type_bonus = _TYPE_PRIORITY.get(event.event_type, 1)
    return (type_bonus, event.credibility_score, event.published_at or "")


def select_events_for_llm(
    events: list[NewsEvent],
    limit: int = MAX_EVENTS_FOR_LLM,
) -> list[NewsEvent]:
    """Deduplicate headlines and keep the highest-signal overnight stories."""
    seen = set()
    unique: list[NewsEvent] = []
    for event in events:
        key = re.sub(r"\s+", " ", (event.headline or "").lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(event)
    unique.sort(key=_event_rank, reverse=True)
    preferred = [e for e in unique if e.event_type != EventType.OTHER]
    filler = [e for e in unique if e.event_type == EventType.OTHER]
    chosen = (preferred + filler)[:limit]
    print(
        f"[ingestion] selected {len(chosen)}/{len(events)} events for LLM "
        f"({len(preferred)} classified, {len(unique)} unique headlines)",
        file=sys.stderr,
    )
    return chosen


def ingest_all_sources(lookback_hours: Optional[int] = None) -> list[NewsEvent]:
    """
    Fetch every configured RSS source, normalize, filter to the overnight
    window, then rank a digest for the AI stage.

    A single source failure must not abort the run.
    """
    if lookback_hours is None:
        lookback_hours = overnight_lookback_hours()

    events: list[NewsEvent] = []
    for source in RSS_SOURCES:
        try:
            raw_entries = fetch_raw_feed_items(source)
        except Exception as exc:
            print(f"[ingestion] {source['name']}: skipped ({exc})", file=sys.stderr)
            continue
        print(
            f"[ingestion] {source['name']}: {len(raw_entries)} raw entries",
            file=sys.stderr,
        )
        for entry in raw_entries:
            event = normalize_entry(entry, source)
            if not event.headline:
                continue
            if is_within_lookback_window(event, lookback_hours=lookback_hours):
                events.append(event)

    if not events:
        print(
            "[ingestion] WARNING: no overnight news items survived lookback; "
            "LLM will have no event tape",
            file=sys.stderr,
        )
        return []

    return select_events_for_llm(events)
