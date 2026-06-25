"""
pipeline/ingestion.py

FR-01.2 — News/event ingestion and normalization.

Pulls from free RSS feeds (per PRD Section 3 budget: $0/mo data sources)
and normalizes every item into the NewsEvent schema. Source list is
intentionally a small, curated set of credible financial wires —
expandable later, but the MVP explicitly favors precision over breadth
(PRD: "fewer, more credible sources over a noisy aggregate").

Network calls use `feedparser` + `requests`; both are pure-Python and
free. No paid news API is used in the MVP per the infra budget cap.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from marketpulse.models.schemas import EventType, GeographicOrigin, NewsEvent

# Curated RSS sources (FR-01.2). Each entry carries a static credibility
# score and a default geographic_origin/event_type used when classification
# heuristics below don't find a stronger signal.
RSS_SOURCES = [
    {
        "name": "Reuters Business",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "credibility_score": 0.95,
        "default_origin": GeographicOrigin.GLOBAL,
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
        "name": "RBI Press Releases",
        "url": "https://www.rbi.org.in/pressreleases_rss.xml",
        "credibility_score": 0.99,
        "default_origin": GeographicOrigin.INDIA,
    },
]

# Simple keyword heuristics for event_type classification (FR-01.2). The
# AI engine (FR-02.2) does the real sentiment work; this is a cheap
# pre-classification pass to route/prioritize events before the LLM call,
# and to flag INDIA_DOMESTIC events for the FR-02.6 override check.
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


def classify_event_type(headline: str, body: str) -> EventType:
    text = f"{headline} {body}".lower()
    for event_type, keywords in _EVENT_TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return event_type
    return EventType.OTHER


def fetch_raw_feed_items(source: dict) -> list[dict]:
    """
    Fetch and parse a single RSS source. Returns a list of raw entry dicts
    (feedparser-style). Isolated into its own function so it's easy to
    mock in tests without hitting the network.
    """
    import feedparser  # local import: optional dependency, not needed for unit tests

    parsed = feedparser.parse(source["url"])
    return list(parsed.entries)


def normalize_entry(entry: dict, source: dict) -> NewsEvent:
    headline = getattr(entry, "title", entry.get("title", "") if isinstance(entry, dict) else "")
    summary = getattr(entry, "summary", entry.get("summary", "") if isinstance(entry, dict) else "")
    link = getattr(entry, "link", entry.get("link", "") if isinstance(entry, dict) else "")

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
    )


def is_within_lookback_window(event: NewsEvent, lookback_hours: int = 16) -> bool:
    """
    FR-01.2: only events published within the lookback window (overnight
    since previous IST close, default 16h) are relevant to a pre-market
    briefing. Older items are discarded to avoid stale news pollution.
    """
    try:
        ts = datetime.fromisoformat(event.ingestion_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return True  # fail open — don't drop events on a parse error
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    return ts >= cutoff


def ingest_all_sources(lookback_hours: int = 16) -> list[NewsEvent]:
    """
    Top-level ingestion entry point. Fetches every configured RSS source,
    normalizes entries, and filters to the lookback window.

    Resilience: a single source failing to fetch (network blip, feed down)
    must not abort the whole run — log and continue (pipeline must still
    assemble at 06:50 IST even with partial data, per Section 3 reliability
    goals).
    """
    events: list[NewsEvent] = []
    for source in RSS_SOURCES:
        try:
            raw_entries = fetch_raw_feed_items(source)
        except Exception:
            continue  # source-level failure is non-fatal; see module docstring
        for entry in raw_entries:
            event = normalize_entry(entry, source)
            if is_within_lookback_window(event, lookback_hours=lookback_hours):
                events.append(event)
    return events
