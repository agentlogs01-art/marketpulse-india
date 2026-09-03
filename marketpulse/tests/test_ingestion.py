"""
tests/test_ingestion.py

Overnight lookback must use RSS published dates (not ingest-now), keep
weekend news on Monday, and pass a ranked digest to the LLM.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import struct_time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.models.schemas import EventType, GeographicOrigin, NewsEvent
from marketpulse.pipeline.ingestion import (
    is_within_lookback_window,
    normalize_entry,
    overnight_lookback_hours,
    published_at_from_entry,
    select_events_for_llm,
)
from marketpulse.utils.timeutils import IST


def _event(**kwargs) -> NewsEvent:
    defaults = dict(
        headline="Fed holds rates",
        body_summary="The Federal Reserve kept interest rates unchanged.",
        event_type=EventType.CENTRAL_BANK,
        geographic_origin=GeographicOrigin.US,
        credibility_score=0.95,
    )
    defaults.update(kwargs)
    return NewsEvent(**defaults)


class TestPublishedTimestamps(unittest.TestCase):
    def test_reads_published_parsed(self):
        entry = SimpleNamespace(
            title="Headline",
            summary="Summary",
            link="https://example.com",
            published_parsed=struct_time((2026, 8, 27, 18, 0, 0, 0, 0, 0)),
        )
        iso = published_at_from_entry(entry)
        self.assertEqual(iso, "2026-08-27T18:00:00Z")

    def test_normalize_stores_published_at(self):
        entry = SimpleNamespace(
            title="RBI keeps repo rate unchanged",
            summary="Policy held.",
            link="https://rbi.org.in/x",
            published_parsed=struct_time((2026, 8, 27, 12, 0, 0, 0, 0, 0)),
        )
        source = {
            "name": "RBI Press Releases",
            "credibility_score": 0.99,
            "default_origin": GeographicOrigin.INDIA,
        }
        event = normalize_entry(entry, source)
        self.assertEqual(event.published_at, "2026-08-27T12:00:00Z")
        self.assertEqual(event.event_type, EventType.INDIA_DOMESTIC)


class TestLookbackWindow(unittest.TestCase):
    def test_drops_stale_published_items(self):
        old = _event(published_at="2020-01-01T00:00:00Z")
        self.assertFalse(is_within_lookback_window(old, lookback_hours=16))

    def test_keeps_recent_published_items(self):
        recent = datetime.now(timezone.utc) - timedelta(hours=3)
        event = _event(published_at=recent.strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertTrue(is_within_lookback_window(event, lookback_hours=16))

    def test_missing_published_at_fails_open(self):
        event = _event(published_at=None)
        self.assertTrue(is_within_lookback_window(event, lookback_hours=16))

    def test_monday_lookback_covers_friday_close(self):
        monday_premarket = datetime(2026, 8, 24, 6, 45, tzinfo=IST)  # Monday
        hours = overnight_lookback_hours(monday_premarket)
        self.assertGreaterEqual(hours, 60)

    def test_weekday_lookback_is_overnight(self):
        tuesday = datetime(2026, 8, 25, 6, 45, tzinfo=IST)
        hours = overnight_lookback_hours(tuesday)
        self.assertGreaterEqual(hours, 16)
        self.assertLess(hours, 30)


class TestSelectEventsForLlm(unittest.TestCase):
    def test_prefers_macro_over_unclassified_and_dedupes(self):
        events = [
            _event(headline="Corp filing A", event_type=EventType.OTHER, credibility_score=1.0),
            _event(headline="Corp filing B", event_type=EventType.OTHER, credibility_score=1.0),
            _event(
                headline="Fed holds rates",
                event_type=EventType.CENTRAL_BANK,
                credibility_score=0.95,
            ),
            _event(
                headline="Fed holds rates",
                event_type=EventType.CENTRAL_BANK,
                credibility_score=0.95,
            ),
            _event(
                headline="Crude jumps on OPEC cut",
                event_type=EventType.COMMODITY,
                credibility_score=0.88,
            ),
        ]
        chosen = select_events_for_llm(events, limit=3)
        headlines = [e.headline for e in chosen]
        self.assertEqual(headlines[0], "Fed holds rates")
        self.assertIn("Crude jumps on OPEC cut", headlines)
        self.assertEqual(len(headlines), 3)
        self.assertEqual(len(set(headlines)), 3)


class TestBuildUserPromptIncludesNews(unittest.TestCase):
    def test_prompt_contains_headline_and_snapshot(self):
        from marketpulse.ai_engine.llm_client import _build_user_prompt

        event = _event(headline="Brent crude surges 3%", published_at="2026-08-27T22:00:00Z")
        prompt = _build_user_prompt(
            event,
            market_context="Overnight market snapshot:\nDow Jones (US): 39000.00 index pts (+0.40%)",
        )
        self.assertIn("Brent crude surges 3%", prompt)
        self.assertIn("Dow Jones (US): 39000.00", prompt)
        self.assertIn("2026-08-27T22:00:00Z", prompt)


if __name__ == "__main__":
    unittest.main()
