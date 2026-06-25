"""
delivery/text_render.py

WhatsApp and Telegram are chat-based channels -- they don't render the
inline-styled HTML email_system/render.py produces. This module builds a
plain-text (Telegram: Markdown-lite) version of the SAME pipeline output
dict, so all three channels stay perfectly in sync content-wise; only the
formatting differs.

Deliberately reuses the exact same source fields (reconciliation,
gift_nifty, sector_scorecards, paragraph_4_text, domestic_override) as
email_system/render.py rather than re-deriving anything, so there is
never a risk of the chat versions saying something different from the
email version of the same day's briefing.
"""

from __future__ import annotations

from marketpulse.models.schemas import BIAS_PLAIN_ENGLISH, Direction

DIRECTION_ARROW = {
    Direction.POSITIVE: "\u2B06\uFE0F",
    Direction.NEGATIVE: "\u2B07\uFE0F",
    Direction.NEUTRAL: "\u27A1\uFE0F",
}

DISCLAIMER_TEXT = (
    "MarketPulse India is for educational purposes only and is not investment advice. "
    "Markets are inherently unpredictable; please consult a SEBI-registered investment "
    "adviser before making any investment decisions."
)


def render_plain_text(pipeline_output: dict) -> str:
    """
    Renders a plain-text digest with no HTML/Markdown markup at all --
    suitable for any channel, used as the WhatsApp message body (Twilio's
    WhatsApp templates are plain text plus a very limited *bold*/_italic_
    subset, so plain text is the safest universal baseline).
    """
    reconciliation = pipeline_output["reconciliation"]
    gift_nifty = pipeline_output["gift_nifty"]
    instrument_snapshots = pipeline_output["instrument_snapshots"]
    sector_scorecards = pipeline_output["sector_scorecards"]
    override = pipeline_output["domestic_override"]

    lines = []
    lines.append(BIAS_PLAIN_ENGLISH[reconciliation.bias_label])
    lines.append("")

    lines.append("MARKET SNAPSHOT")
    for s in instrument_snapshots:
        arrow = "UP" if s.pct_change > 0 else ("DOWN" if s.pct_change < 0 else "FLAT")
        delayed = " (delayed)" if s.is_delayed else ""
        lines.append(f"- {s.name}: {s.value:,.2f} {s.unit} ({arrow} {s.pct_change:+.2f}%){delayed}")
    lines.append("")

    direction_word = "higher" if gift_nifty.pct_change_vs_prev_close >= 0 else "lower"
    estimate_note = " (estimated proxy)" if gift_nifty.is_estimated else ""
    lines.append(
        f"GIFT NIFTY: {gift_nifty.last_traded_price:,.2f} "
        f"({gift_nifty.pct_change_vs_prev_close:+.2f}% vs yesterday's close of "
        f"{gift_nifty.prev_nifty_close:,.2f}) -- pointing {direction_word}.{estimate_note}"
    )
    lines.append("")

    lines.append("TODAY'S STORY")
    lines.append("Good morning! Here's what's moving Indian markets ahead of today's open.")
    if override.active:
        lines.append(override.narrative_paragraph_2_override or "")
    else:
        lines.append("Overnight, global markets sent mixed-to-moderate signals across major regions.")
    lines.append(f"The biggest driver today: {reconciliation.top_signal_plain_english}")
    lines.append(pipeline_output["paragraph_4_text"])
    lines.append("")

    if sector_scorecards:
        lines.append("SECTOR-BY-SECTOR IMPACT")
        for scorecard in sector_scorecards.values():
            arrow_word = {"POSITIVE": "UP", "NEGATIVE": "DOWN", "NEUTRAL": "FLAT"}[scorecard.direction.value]
            mixed_note = " (mixed signals)" if scorecard.is_mixed else ""
            lines.append(f"- {scorecard.sector.value} [{arrow_word}, {scorecard.impact_level} impact]{mixed_note}")
            lines.append(f"  {scorecard.rationale_plain_english}")
        lines.append("")

    lines.append(DISCLAIMER_TEXT)
    return "\n".join(lines)


def render_telegram_markdown(pipeline_output: dict) -> str:
    """
    Telegram's Bot API supports a constrained Markdown subset (MarkdownV2):
    *bold*, _italic_, and escaped punctuation. This produces a lightly
    formatted version more pleasant to read in a chat than the plain-text
    version, while staying within MarkdownV2's escaping rules.
    """
    reconciliation = pipeline_output["reconciliation"]
    gift_nifty = pipeline_output["gift_nifty"]
    instrument_snapshots = pipeline_output["instrument_snapshots"]
    sector_scorecards = pipeline_output["sector_scorecards"]
    override = pipeline_output["domestic_override"]

    def esc(text: str) -> str:
        """Escape MarkdownV2 reserved characters."""
        reserved = r"_*[]()~`>#+-=|{}.!"
        return "".join(f"\\{c}" if c in reserved else c for c in text)

    lines = []
    lines.append(f"*{esc(BIAS_PLAIN_ENGLISH[reconciliation.bias_label])}*")
    lines.append("")

    lines.append("*Market Snapshot*")
    for s in instrument_snapshots:
        direction = Direction.POSITIVE if s.pct_change > 0 else (Direction.NEGATIVE if s.pct_change < 0 else Direction.NEUTRAL)
        arrow = DIRECTION_ARROW[direction]
        lines.append(f"{esc('-')} {esc(s.name)}: {esc(f'{s.value:,.2f} {s.unit}')} ({arrow} {esc(f'{s.pct_change:+.2f}%')})")
    lines.append("")

    direction_word = "higher" if gift_nifty.pct_change_vs_prev_close >= 0 else "lower"
    lines.append(
        f"*GIFT Nifty*: {esc(f'{gift_nifty.last_traded_price:,.2f}')} "
        f"({esc(f'{gift_nifty.pct_change_vs_prev_close:+.2f}%')} vs yesterday's close of "
        f"{esc(f'{gift_nifty.prev_nifty_close:,.2f}')}) — pointing {esc(direction_word)}\\."
    )
    lines.append("")

    lines.append("*Today's Story*")
    lines.append(esc("Good morning! Here's what's moving Indian markets ahead of today's open."))
    if override.active:
        lines.append(esc(override.narrative_paragraph_2_override or ""))
    else:
        lines.append(esc("Overnight, global markets sent mixed-to-moderate signals across major regions."))
    lines.append(esc(f"The biggest driver today: {reconciliation.top_signal_plain_english}"))
    lines.append(esc(pipeline_output["paragraph_4_text"]))
    lines.append("")

    if sector_scorecards:
        lines.append("*Sector\\-by\\-Sector Impact*")
        for scorecard in sector_scorecards.values():
            arrow = DIRECTION_ARROW[scorecard.direction]
            mixed_note = esc(" (mixed signals)") if scorecard.is_mixed else ""
            lines.append(f"{arrow} *{esc(scorecard.sector.value)}* {esc(f'[{scorecard.impact_level} impact]')}{mixed_note}")
            lines.append(esc(scorecard.rationale_plain_english))
        lines.append("")

    lines.append(f"_{esc(DISCLAIMER_TEXT)}_")
    return "\n".join(lines)
