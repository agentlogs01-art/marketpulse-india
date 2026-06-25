"""
tests/test_text_render.py

Tests delivery/text_render.py against a synthetic pipeline_output
shape -- verifying the chat-channel renderers stay content-equivalent to
the HTML email (same bias label, same paragraph 4 text, same sector
rationale) while only the markup differs.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.constants.paragraph4_tokens import FLAT_OVERRIDE_TOKEN, resolve_paragraph_4
from marketpulse.delivery.text_render import render_plain_text, render_telegram_markdown
from marketpulse.models.schemas import (
    BiasLabel,
    Direction,
    DomesticOverrideResult,
    GiftNiftySnapshot,
    InstrumentSnapshot,
    ReconciliationResult,
    Sector,
    SectorScorecard,
)


def make_pipeline_output():
    gift = GiftNiftySnapshot(
        last_traded_price=24850.5,
        pct_change_vs_prev_close=0.05,
        prev_nifty_close=24838.2,
        captured_at_ist="2026-06-20T06:45:00+05:30",
    )
    instruments = [
        InstrumentSnapshot(name="Dow Jones (US)", value=39850.2, pct_change=0.34, unit="index pts"),
        InstrumentSnapshot(name="Brent Crude Oil", value=82.4, pct_change=-1.1, unit="USD/barrel"),
    ]
    scorecards = {
        Sector.BANKING: SectorScorecard(
            sector=Sector.BANKING,
            direction=Direction.POSITIVE,
            impact_level="Medium",
            rationale_plain_english="Lower bond yields ease funding costs for banks.",
            is_mixed=False,
            score=1.2,
        )
    }
    override = DomesticOverrideResult(active=False)
    reconciliation = ReconciliationResult(
        bias_label=BiasLabel.FLAT,
        composite_score=0.05,
        flat_override_triggered=True,
        paragraph_4_token=FLAT_OVERRIDE_TOKEN,
        top_signal_plain_english="quiet overnight trade",
        domestic_override=override,
    )
    return {
        "gift_nifty": gift,
        "instrument_snapshots": instruments,
        "sector_scorecards": scorecards,
        "reconciliation": reconciliation,
        "domestic_override": override,
        "paragraph_4_text": resolve_paragraph_4(reconciliation.paragraph_4_token),
    }


class TestRenderPlainText(unittest.TestCase):
    def setUp(self):
        self.output = make_pipeline_output()

    def test_includes_bias_label_text(self):
        text = render_plain_text(self.output)
        self.assertIn("Market likely to open flat", text)

    def test_includes_all_instruments(self):
        text = render_plain_text(self.output)
        self.assertIn("Dow Jones (US)", text)
        self.assertIn("Brent Crude Oil", text)

    def test_includes_sector_rationale(self):
        text = render_plain_text(self.output)
        self.assertIn("Lower bond yields ease funding costs", text)

    def test_includes_paragraph_4_resolution(self):
        text = render_plain_text(self.output)
        self.assertIn("flat with no clear direction", text)

    def test_includes_disclaimer(self):
        text = render_plain_text(self.output)
        self.assertIn("educational purposes only", text)

    def test_no_html_or_markdown_markup(self):
        text = render_plain_text(self.output)
        self.assertNotIn("<", text)
        self.assertNotIn("*", text)

    def test_omits_sector_section_when_no_scorecards(self):
        output = make_pipeline_output()
        output["sector_scorecards"] = {}
        text = render_plain_text(output)
        self.assertNotIn("SECTOR-BY-SECTOR", text)


class TestRenderTelegramMarkdown(unittest.TestCase):
    def setUp(self):
        self.output = make_pipeline_output()

    def test_includes_instrument_names(self):
        text = render_telegram_markdown(self.output)
        self.assertIn("Dow Jones", text)
        self.assertIn("Brent Crude Oil", text)

    def test_includes_bold_markers_around_headers(self):
        text = render_telegram_markdown(self.output)
        self.assertIn("*Market Snapshot*", text)
        self.assertIn("*GIFT Nifty*", text)

    def test_includes_sector_rationale_escaped(self):
        text = render_telegram_markdown(self.output)
        self.assertIn("Lower bond yields ease funding costs for banks", text)

    def test_period_characters_are_escaped(self):
        text = render_telegram_markdown(self.output)
        # Raw, unescaped "82.4" would appear as-is; MarkdownV2 escaping
        # inserts a backslash before the literal period.
        self.assertIn("82\\.4", text)


if __name__ == "__main__":
    unittest.main()
