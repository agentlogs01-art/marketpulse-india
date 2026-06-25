"""
email_system/render.py

FR-03.1 -- Email Template Structure. Builds the final plain-English,
beginner-friendly HTML email from the pipeline's assembled output:

  Section 1: Subject line + bias badge
  Section 2: Market Snapshot table (global indices, commodities, currency)
  Section 3: GIFT Nifty callout box
  Section 4: AI Narrative (4 paragraphs -- paragraph 4 is sentinel-resolved)
  Section 5: Sector-by-sector impact scorecards (only sectors affected today)
  Section 6: Footer / disclaimer

Output is intentionally simple inline-styled HTML (no external CSS) for
maximum email-client compatibility, consistent with a $0 email-template
budget -- no paid transactional-email template service required.
"""

from __future__ import annotations

from marketpulse.models.schemas import (
    BIAS_COLOR,
    BIAS_PLAIN_ENGLISH,
    Direction,
    GiftNiftySnapshot,
    InstrumentSnapshot,
    ReconciliationResult,
)

DISCLAIMER_TEXT = (
    "MarketPulse India is for educational purposes only and is not "
    "investment advice. Markets are inherently unpredictable; this "
    "briefing reflects overnight signals as of send time and may not "
    "play out as described. Please consult a SEBI-registered investment "
    "adviser before making any investment decisions."
)

DIRECTION_ARROW = {
    Direction.POSITIVE: "\u2B06\uFE0F",
    Direction.NEGATIVE: "\u2B07\uFE0F",
    Direction.NEUTRAL: "\u27A1\uFE0F",
}

IMPACT_LEVEL_COLOR = {
    "Low": "#9E9E9E",
    "Medium": "#E0B400",
    "High": "#C0392B",
}


def render_subject_line(reconciliation: ReconciliationResult) -> str:
    plain = BIAS_PLAIN_ENGLISH[reconciliation.bias_label]
    # Strip the emoji prefix for the subject line; keep it in the body badge.
    text_only = plain.split(" ", 1)[1] if " " in plain else plain
    return f"MarketPulse India: {text_only}"


def render_bias_badge(reconciliation: ReconciliationResult) -> str:
    color = BIAS_COLOR[reconciliation.bias_label]
    label = BIAS_PLAIN_ENGLISH[reconciliation.bias_label]
    return (
        f'<div style="background-color:{color};color:#ffffff;padding:14px 20px;'
        f'border-radius:8px;font-size:18px;font-weight:bold;text-align:center;'
        f'margin-bottom:16px;">{label}</div>'
    )


def render_market_snapshot_table(snapshots: list) -> str:
    rows = []
    for s in snapshots:
        arrow = "\u2B06\uFE0F" if s.pct_change > 0 else ("\u2B07\uFE0F" if s.pct_change < 0 else "\u27A1\uFE0F")
        delayed_badge = (
            ' <span style="color:#E07B00;font-size:12px;">\u26A0\uFE0F Data Delayed</span>'
            if s.is_delayed else ""
        )
        color = "#0B6E2D" if s.pct_change >= 0 else "#C0392B"
        rows.append(
            '<tr style="border-bottom:1px solid #eee;">'
            f'<td style="padding:8px;">{s.name}</td>'
            f'<td style="padding:8px;text-align:right;">{s.value:,.2f} {s.unit}</td>'
            f'<td style="padding:8px;text-align:right;color:{color};">'
            f'{arrow} {s.pct_change:+.2f}%{delayed_badge}</td>'
            '</tr>'
        )
    return (
        '<table style="width:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">'
        '<thead><tr style="background-color:#f5f5f5;">'
        '<th style="padding:8px;text-align:left;">Instrument</th>'
        '<th style="padding:8px;text-align:right;">Value</th>'
        '<th style="padding:8px;text-align:right;">Change</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table>'
    )


def render_gift_nifty_callout(gift_nifty: GiftNiftySnapshot) -> str:
    direction_word = "higher" if gift_nifty.pct_change_vs_prev_close >= 0 else "lower"
    estimate_note = (
        ' <em>(Estimated proxy \u2014 live GIFT Nifty data unavailable)</em>'
        if gift_nifty.is_estimated else ""
    )
    return (
        '<div style="background-color:#F0F4F8;border-left:4px solid #2E5C8A;'
        'padding:12px 16px;margin:16px 0;font-family:Arial,sans-serif;font-size:14px;">'
        '<strong>GIFT Nifty</strong> (a futures contract that previews how Indian markets '
        'will open, traded at GIFT City, India from 06:30 AM IST): '
        f'<strong>{gift_nifty.last_traded_price:,.2f}</strong> '
        f'({gift_nifty.pct_change_vs_prev_close:+.2f}% vs yesterday\'s Nifty 50 close of '
        f'{gift_nifty.prev_nifty_close:,.2f}) \u2014 pointing {direction_word}.{estimate_note}'
        '</div>'
    )


def render_narrative(paragraphs: list) -> str:
    blocks = "".join(
        f'<p style="font-family:Arial,sans-serif;font-size:15px;line-height:1.6;color:#222;">{p}</p>'
        for p in paragraphs
    )
    return blocks


def render_sector_scorecards(scorecards: dict) -> str:
    if not scorecards:
        return (
            '<p style="font-family:Arial,sans-serif;font-size:14px;color:#666;">'
            'No major sector-specific signals identified for today.</p>'
        )
    cards = []
    for scorecard in scorecards.values():
        arrow = DIRECTION_ARROW[scorecard.direction]
        impact_color = IMPACT_LEVEL_COLOR[scorecard.impact_level]
        mixed_note = (
            ' <span style="font-size:12px;color:#E07B00;">(Mixed signals today)</span>'
            if scorecard.is_mixed else ""
        )
        cards.append(
            '<div style="border:1px solid #eee;border-radius:6px;padding:12px;margin-bottom:10px;'
            'font-family:Arial,sans-serif;">'
            f'<div style="font-weight:bold;font-size:15px;">{arrow} {scorecard.sector.value} '
            f'<span style="background-color:{impact_color};color:#fff;font-size:11px;'
            f'padding:2px 8px;border-radius:10px;margin-left:8px;">{scorecard.impact_level} impact</span>'
            f'{mixed_note}</div>'
            f'<div style="font-size:13px;color:#444;margin-top:4px;">{scorecard.rationale_plain_english}</div>'
            '</div>'
        )
    return "".join(cards)


def render_footer() -> str:
    return (
        '<hr style="border:none;border-top:1px solid #eee;margin:24px 0;">'
        f'<p style="font-family:Arial,sans-serif;font-size:11px;color:#999;line-height:1.5;">{DISCLAIMER_TEXT}</p>'
    )


def render_email_html(pipeline_output: dict) -> str:
    """
    Assemble the full HTML email from the orchestrator's output dict.
    Expects keys: gift_nifty, instrument_snapshots, sector_scorecards,
    reconciliation, paragraph_4_text, domestic_override.
    """
    reconciliation = pipeline_output["reconciliation"]
    gift_nifty = pipeline_output["gift_nifty"]
    instrument_snapshots = pipeline_output["instrument_snapshots"]
    sector_scorecards = pipeline_output["sector_scorecards"]
    override = pipeline_output["domestic_override"]

    paragraph_1 = "Good morning! Here's what's moving Indian markets ahead of today's open."
    paragraph_2 = (
        override.narrative_paragraph_2_override
        if override.active
        else "Overnight, global markets sent mixed-to-moderate signals across major regions."
    )
    paragraph_3 = f"The biggest driver today: {reconciliation.top_signal_plain_english}"
    paragraph_4 = pipeline_output["paragraph_4_text"]

    body = (
        '<div style="max-width:640px;margin:0 auto;padding:20px;">'
        + render_bias_badge(reconciliation)
        + '<h2 style="font-family:Arial,sans-serif;font-size:16px;color:#333;">Market Snapshot</h2>'
        + render_market_snapshot_table(instrument_snapshots)
        + render_gift_nifty_callout(gift_nifty)
        + '<h2 style="font-family:Arial,sans-serif;font-size:16px;color:#333;">Today\'s Story</h2>'
        + render_narrative([paragraph_1, paragraph_2, paragraph_3, paragraph_4])
        + '<h2 style="font-family:Arial,sans-serif;font-size:16px;color:#333;">Sector-by-Sector Impact</h2>'
        + render_sector_scorecards(sector_scorecards)
        + render_footer()
        + '</div>'
    )
    return body


def render_subject_and_html(pipeline_output: dict) -> tuple:
    subject = render_subject_line(pipeline_output["reconciliation"])
    html = render_email_html(pipeline_output)
    return subject, html
