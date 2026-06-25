"""
tests/test_bias_engine.py

FR-02.5 (Branch A flat override / Branch B divergence) and FR-02.6
(domestic systemic override) deterministic logic tests.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.ai_engine.bias_engine import (
    aggregate_sector_scores,
    detect_domestic_override,
    reconcile_bias,
)
from marketpulse.constants.paragraph4_tokens import DIVERGENCE_TOKEN_PREFIX, FLAT_OVERRIDE_TOKEN
from marketpulse.models.schemas import (
    BiasLabel,
    Direction,
    DomesticOverrideResult,
    EventAnalysis,
    EventType,
    GeographicOrigin,
    GiftNiftySnapshot,
    NewsEvent,
    Sector,
    SectorImpact,
    Sentiment,
)


def make_event(event_type=EventType.MACRO_DATA, credibility=0.9) -> NewsEvent:
    return NewsEvent(
        headline="Test event",
        body_summary="Test summary",
        event_type=event_type,
        geographic_origin=GeographicOrigin.GLOBAL,
        credibility_score=credibility,
    )


def make_analysis(event_id, bias, intensity=3, sectors=None) -> EventAnalysis:
    return EventAnalysis(
        event_id=event_id,
        overall_sentiment=Sentiment.NEUTRAL,
        sentiment_intensity=intensity,
        confidence=0.8,
        affected_sectors=sectors or [],
        nifty50_overall_bias=bias,
        one_line_summary_for_beginner="Test summary line",
    )


class TestFlatOverride(unittest.TestCase):
    def test_flat_gift_nifty_triggers_branch_a(self):
        gift = GiftNiftySnapshot(
            last_traded_price=24800.0,
            pct_change_vs_prev_close=0.05,  # within FLAT_THRESHOLD_PCT
            prev_nifty_close=24790.0,
            captured_at_ist="2026-06-20T06:45:00+05:30",
        )
        result = reconcile_bias(gift, [], DomesticOverrideResult(active=False))
        self.assertTrue(result.flat_override_triggered)
        self.assertEqual(result.bias_label, BiasLabel.FLAT)
        self.assertEqual(result.paragraph_4_token, FLAT_OVERRIDE_TOKEN)


class TestDivergence(unittest.TestCase):
    def test_opposing_signals_trigger_branch_b(self):
        event = make_event()
        analysis = make_analysis(event.event_id, BiasLabel.GAP_UP_STRONG, intensity=4)
        gift = GiftNiftySnapshot(
            last_traded_price=24500.0,
            pct_change_vs_prev_close=-1.2,  # strong move down, opposite of bullish LLM read
            prev_nifty_close=24790.0,
            captured_at_ist="2026-06-20T06:45:00+05:30",
        )
        result = reconcile_bias(gift, [analysis], DomesticOverrideResult(active=False))
        self.assertTrue(result.divergence_flag)
        self.assertEqual(result.bias_label, BiasLabel.GAP_DOWN_STRONG)
        self.assertTrue(result.paragraph_4_token.startswith(DIVERGENCE_TOKEN_PREFIX))
        self.assertEqual(result.divergence_direction, "lower")

    def test_aligned_signals_do_not_trigger_divergence(self):
        event = make_event()
        analysis = make_analysis(event.event_id, BiasLabel.GAP_UP_STRONG, intensity=4)
        gift = GiftNiftySnapshot(
            last_traded_price=25100.0,
            pct_change_vs_prev_close=1.3,
            prev_nifty_close=24790.0,
            captured_at_ist="2026-06-20T06:45:00+05:30",
        )
        result = reconcile_bias(gift, [analysis], DomesticOverrideResult(active=False))
        self.assertFalse(result.divergence_flag)
        self.assertFalse(result.flat_override_triggered)
        self.assertEqual(result.bias_label, BiasLabel.GAP_UP_STRONG)


class TestDomesticOverride(unittest.TestCase):
    def test_high_intensity_domestic_event_triggers_override(self):
        domestic_event = make_event(event_type=EventType.INDIA_DOMESTIC, credibility=0.99)
        global_event = make_event(event_type=EventType.MACRO_DATA, credibility=0.9)

        domestic_analysis = make_analysis(domestic_event.event_id, BiasLabel.GAP_DOWN_STRONG, intensity=5)
        global_analysis = make_analysis(global_event.event_id, BiasLabel.GAP_UP_MILD, intensity=2)

        events_by_id = {domestic_event.event_id: domestic_event, global_event.event_id: global_event}
        override = detect_domestic_override(events_by_id, [domestic_analysis, global_analysis])

        self.assertTrue(override.active)
        self.assertEqual(override.trigger_event.event_id, domestic_event.event_id)
        self.assertAlmostEqual(override.weights["domestic_event"], 0.70)

    def test_low_intensity_domestic_event_does_not_trigger(self):
        domestic_event = make_event(event_type=EventType.INDIA_DOMESTIC)
        analysis = make_analysis(domestic_event.event_id, BiasLabel.FLAT, intensity=2)
        events_by_id = {domestic_event.event_id: domestic_event}
        override = detect_domestic_override(events_by_id, [analysis])
        self.assertFalse(override.active)

    def test_no_events_returns_inactive_override(self):
        override = detect_domestic_override({}, [])
        self.assertFalse(override.active)


class TestSectorAggregation(unittest.TestCase):
    def test_weighted_average_direction(self):
        event = make_event(credibility=1.0)
        impact = SectorImpact(
            sector=Sector.BANKING,
            direction=Direction.POSITIVE,
            impact_magnitude=4,
            rationale_plain_english="Rate cut helps lending margins.",
        )
        analysis = make_analysis(event.event_id, BiasLabel.GAP_UP_MILD, sectors=[impact])
        scorecards = aggregate_sector_scores([analysis], {event.event_id: event})
        self.assertIn(Sector.BANKING, scorecards)
        self.assertEqual(scorecards[Sector.BANKING].direction, Direction.POSITIVE)

    def test_unaffected_sector_is_omitted(self):
        event = make_event()
        impact = SectorImpact(
            sector=Sector.IT,
            direction=Direction.NEGATIVE,
            impact_magnitude=2,
            rationale_plain_english="Stronger dollar pressures margins.",
        )
        analysis = make_analysis(event.event_id, BiasLabel.FLAT, sectors=[impact])
        scorecards = aggregate_sector_scores([analysis], {event.event_id: event})
        self.assertNotIn(Sector.BANKING, scorecards)
        self.assertNotIn(Sector.AUTO, scorecards)
        self.assertIn(Sector.IT, scorecards)

    def test_mixed_signals_flag(self):
        event1 = make_event(credibility=0.9)
        event2 = make_event(credibility=0.9)
        impact1 = SectorImpact(Sector.ENERGY, Direction.POSITIVE, 3, "Oil prices up.")
        impact2 = SectorImpact(Sector.ENERGY, Direction.NEGATIVE, 3, "Demand worries.")
        analysis1 = make_analysis(event1.event_id, BiasLabel.FLAT, sectors=[impact1])
        analysis2 = make_analysis(event2.event_id, BiasLabel.FLAT, sectors=[impact2])
        events_by_id = {event1.event_id: event1, event2.event_id: event2}
        scorecards = aggregate_sector_scores([analysis1, analysis2], events_by_id)
        self.assertTrue(scorecards[Sector.ENERGY].is_mixed)


if __name__ == "__main__":
    unittest.main()
