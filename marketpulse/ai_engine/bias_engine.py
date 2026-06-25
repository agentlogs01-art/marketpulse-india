"""
ai_engine/bias_engine.py

Implements three tightly related deterministic (non-LLM) stages:

  FR-02.3 — Sector aggregation: weighted-average per-sector scores across
            all events of the day into a single SectorScorecard per sector.

  FR-02.5 — Bias reconciliation: combine the LLM's aggregate sentiment
            with the live GIFT Nifty snapshot into one final BiasLabel,
            using the Branch A (flat override) / Branch B (divergence)
            logic from the v1.6 hardening, and select the correct
            Paragraph 4 sentinel token (see constants/paragraph4_tokens).

  FR-02.6 — Domestic Systemic Override: if a high-intensity INDIA_DOMESTIC
            event occurs (e.g. RBI surprise rate move, major regulatory
            action), it overrides normal weighting so the domestic event
            dominates the narrative instead of being averaged away by
            global noise.

All thresholds below are taken directly from the PRD; comments cite the
originating FR for traceability.
"""

from __future__ import annotations

from collections import defaultdict

from marketpulse.constants.paragraph4_tokens import (
    FLAT_OVERRIDE_TOKEN,
    STANDARD_TOKEN,
    build_divergence_token,
)
from marketpulse.models.schemas import (
    BiasLabel,
    Direction,
    DomesticOverrideResult,
    EventAnalysis,
    EventType,
    GiftNiftySnapshot,
    NewsEvent,
    ReconciliationResult,
    Sector,
    SectorImpact,
    SectorScorecard,
)

# ---------------------------------------------------------------------------
# FR-02.3 — Sector aggregation thresholds
# ---------------------------------------------------------------------------

IMPACT_LEVEL_THRESHOLDS = {
    # weighted-average |score| upper bound -> label
    "Low": 2.0,
    "Medium": 3.5,
    # anything above Medium threshold -> "High"
}

# Credibility-based weighting: higher source credibility => higher weight
# in the per-sector weighted average (prevents a single low-credibility
# rumor wire from swinging the sector score as much as a central-bank
# release would).
DEFAULT_CREDIBILITY_WEIGHT = 1.0


def _impact_level_from_score(abs_score: float) -> str:
    if abs_score <= IMPACT_LEVEL_THRESHOLDS["Low"]:
        return "Low"
    if abs_score <= IMPACT_LEVEL_THRESHOLDS["Medium"]:
        return "Medium"
    return "High"


def aggregate_sector_scores(
    analyses: list[EventAnalysis],
    events_by_id: dict[str, NewsEvent],
) -> dict[Sector, SectorScorecard]:
    """
    FR-02.3: For each of the 5 MVP sectors, compute a weighted-average
    directional score across every SectorImpact mentioning that sector
    across all of today's analyzed events, weighted by source
    credibility_score. Direction sign convention: POSITIVE=+1,
    NEGATIVE=-1, NEUTRAL=0, multiplied by impact_magnitude (1-5).
    """
    weighted_sums: dict[Sector, float] = defaultdict(float)
    weight_totals: dict[Sector, float] = defaultdict(float)
    rationales: dict[Sector, list[tuple[float, str]]] = defaultdict(list)
    mixed_flags: dict[Sector, set] = defaultdict(set)

    sign = {Direction.POSITIVE: 1, Direction.NEGATIVE: -1, Direction.NEUTRAL: 0}

    for analysis in analyses:
        event = events_by_id.get(analysis.event_id)
        credibility = event.credibility_score if event else DEFAULT_CREDIBILITY_WEIGHT
        weight = max(credibility, 0.1)  # floor weight so no event is fully zeroed out

        for impact in analysis.affected_sectors:
            signed_score = sign[impact.direction] * impact.impact_magnitude
            weighted_sums[impact.sector] += signed_score * weight
            weight_totals[impact.sector] += weight
            rationales[impact.sector].append((weight, impact.rationale_plain_english))
            mixed_flags[impact.sector].add(impact.direction)

    scorecards: dict[Sector, SectorScorecard] = {}
    for sector in Sector:
        total_weight = weight_totals.get(sector, 0.0)
        if total_weight == 0.0:
            continue  # sector unaffected today — omitted from email per FR-03.1

        avg_score = weighted_sums[sector] / total_weight
        abs_score = abs(avg_score)

        if avg_score > 0.25:
            direction = Direction.POSITIVE
        elif avg_score < -0.25:
            direction = Direction.NEGATIVE
        else:
            direction = Direction.NEUTRAL

        is_mixed = len(mixed_flags[sector] - {Direction.NEUTRAL}) > 1

        # Use the rationale from the highest-weighted contributing event.
        top_rationale = max(rationales[sector], key=lambda t: t[0])[1] if rationales[sector] else ""

        scorecards[sector] = SectorScorecard(
            sector=sector,
            direction=direction,
            impact_level=_impact_level_from_score(abs_score),
            rationale_plain_english=top_rationale,
            is_mixed=is_mixed,
            score=avg_score,
        )

    return scorecards


# ---------------------------------------------------------------------------
# FR-02.6 — Domestic Systemic Override
# ---------------------------------------------------------------------------

DOMESTIC_OVERRIDE_INTENSITY_THRESHOLD = 4  # sentiment_intensity >= this triggers override
DOMESTIC_OVERRIDE_WEIGHT = {
    "domestic_event": 0.70,
    "global_composite": 0.30,
}


def detect_domestic_override(
    events_by_id: dict[str, NewsEvent],
    analyses: list[EventAnalysis],
) -> DomesticOverrideResult:
    """
    FR-02.6: Scan today's events for an INDIA_DOMESTIC event_type with
    sentiment_intensity >= threshold (e.g. surprise RBI rate decision,
    major SEBI regulatory action). If found, the override activates:
    the domestic event's signal is weighted 70/30 against the rest of
    the global composite for the final bias call, and Paragraph 2 of the
    narrative is forced to lead with the domestic story regardless of
    its chronological position in the day's news flow.
    """
    candidates = []
    for analysis in analyses:
        event = events_by_id.get(analysis.event_id)
        if not event:
            continue
        if (
            event.event_type == EventType.INDIA_DOMESTIC
            and analysis.sentiment_intensity >= DOMESTIC_OVERRIDE_INTENSITY_THRESHOLD
        ):
            candidates.append((analysis.sentiment_intensity, event, analysis))

    if not candidates:
        return DomesticOverrideResult(active=False)

    # Highest-intensity domestic event wins if multiple qualify same day.
    _, trigger_event, trigger_analysis = max(candidates, key=lambda c: c[0])

    return DomesticOverrideResult(
        active=True,
        trigger_event=trigger_event,
        weights=dict(DOMESTIC_OVERRIDE_WEIGHT),
        narrative_paragraph_2_override=trigger_analysis.one_line_summary_for_beginner,
    )


# ---------------------------------------------------------------------------
# FR-02.5 — Bias Reconciliation (Branch A: flat override / Branch B: divergence)
# ---------------------------------------------------------------------------

FLAT_THRESHOLD_PCT = 0.10        # |GIFT Nifty % change| <= this => flat override
DIVERGENCE_THRESHOLD_PCT = 0.30  # GIFT Nifty move beyond this with opposing LLM bias => divergence

_BIAS_DIRECTION_SIGN = {
    BiasLabel.GAP_UP_STRONG: 1,
    BiasLabel.GAP_UP_MILD: 1,
    BiasLabel.FLAT: 0,
    BiasLabel.GAP_DOWN_MILD: -1,
    BiasLabel.GAP_DOWN_STRONG: -1,
}


def _bias_from_gift_nifty_pct(pct_change: float) -> BiasLabel:
    if pct_change >= 1.0:
        return BiasLabel.GAP_UP_STRONG
    if pct_change >= FLAT_THRESHOLD_PCT:
        return BiasLabel.GAP_UP_MILD
    if pct_change <= -1.0:
        return BiasLabel.GAP_DOWN_STRONG
    if pct_change <= -FLAT_THRESHOLD_PCT:
        return BiasLabel.GAP_DOWN_MILD
    return BiasLabel.FLAT


def _composite_llm_bias(
    analyses: list[EventAnalysis],
    override: DomesticOverrideResult,
) -> tuple[BiasLabel, str]:
    """Weighted-average composite of all events' nifty50_overall_bias,
    applying the FR-02.6 domestic override weighting if active."""
    if not analyses:
        return BiasLabel.FLAT, "no significant overnight news"

    if override.active and override.trigger_event:
        dom_score = _BIAS_DIRECTION_SIGN[
            next(a.nifty50_overall_bias for a in analyses if a.event_id == override.trigger_event.event_id)
        ]
        other = [a for a in analyses if a.event_id != override.trigger_event.event_id]
        global_score = (
            sum(_BIAS_DIRECTION_SIGN[a.nifty50_overall_bias] for a in other) / len(other)
            if other else 0
        )
        composite = (
            dom_score * DOMESTIC_OVERRIDE_WEIGHT["domestic_event"]
            + global_score * DOMESTIC_OVERRIDE_WEIGHT["global_composite"]
        )
        top_signal = override.narrative_paragraph_2_override or "a major domestic policy event"
    else:
        composite = sum(_BIAS_DIRECTION_SIGN[a.nifty50_overall_bias] for a in analyses) / len(analyses)
        top_signal = max(analyses, key=lambda a: a.sentiment_intensity).one_line_summary_for_beginner

    if composite > 0.5:
        label = BiasLabel.GAP_UP_STRONG
    elif composite > 0.1:
        label = BiasLabel.GAP_UP_MILD
    elif composite < -0.5:
        label = BiasLabel.GAP_DOWN_STRONG
    elif composite < -0.1:
        label = BiasLabel.GAP_DOWN_MILD
    else:
        label = BiasLabel.FLAT

    return label, top_signal


def reconcile_bias(
    gift_nifty: GiftNiftySnapshot,
    analyses: list[EventAnalysis],
    override: DomesticOverrideResult,
) -> ReconciliationResult:
    """
    FR-02.5 core reconciliation logic.

    Branch A (Flat Override): if GIFT Nifty itself is essentially flat
    (|% change| <= FLAT_THRESHOLD_PCT), the live market signal takes
    absolute precedence over any LLM-derived composite bias — real-time
    price action overrides news-based inference. Paragraph 4 is set to
    the FLAT_OVERRIDE_TOKEN sentinel (resolved with zero LLM calls).

    Branch B (Divergence): if GIFT Nifty has moved meaningfully but in
    the OPPOSITE direction to the LLM composite bias, flag a divergence:
    final bias_label follows the live GIFT Nifty print (markets trade on
    price, not narrative), but Paragraph 4 surfaces the conflicting
    narrative so the reader is warned the move could reverse.

    Otherwise (Standard): GIFT Nifty and the LLM composite agree (or
    there's no live print yet) — blend and use the standard token.
    """
    llm_bias, top_signal = _composite_llm_bias(analyses, override)

    # Branch A — Flat Override
    if abs(gift_nifty.pct_change_vs_prev_close) <= FLAT_THRESHOLD_PCT:
        return ReconciliationResult(
            bias_label=BiasLabel.FLAT,
            composite_score=gift_nifty.pct_change_vs_prev_close,
            flat_override_triggered=True,
            paragraph_4_token=FLAT_OVERRIDE_TOKEN,
            top_signal_plain_english=top_signal,
            domestic_override=override,
        )

    gift_label = _bias_from_gift_nifty_pct(gift_nifty.pct_change_vs_prev_close)
    gift_sign = _BIAS_DIRECTION_SIGN[gift_label]
    llm_sign = _BIAS_DIRECTION_SIGN[llm_bias]

    # Branch B — Divergence: GIFT Nifty moved meaningfully, opposite to LLM read.
    if (
        abs(gift_nifty.pct_change_vs_prev_close) >= DIVERGENCE_THRESHOLD_PCT
        and gift_sign != 0
        and llm_sign != 0
        and gift_sign != llm_sign
    ):
        direction = "higher" if gift_sign > 0 else "lower"
        signal = "opposing" if abs(gift_nifty.pct_change_vs_prev_close) >= 1.0 else "conflicting"
        token = build_divergence_token(
            direction=direction,
            event=top_signal,
            signal=signal,
        )
        return ReconciliationResult(
            bias_label=gift_label,  # live price action wins the headline label
            composite_score=gift_nifty.pct_change_vs_prev_close,
            divergence_flag=True,
            divergence_direction=direction,
            divergence_event=top_signal,
            divergence_signal=signal,
            paragraph_4_token=token,
            top_signal_plain_english=top_signal,
            domestic_override=override,
        )

    # Standard — aligned, blend toward the live print since it's most current.
    return ReconciliationResult(
        bias_label=gift_label,
        composite_score=gift_nifty.pct_change_vs_prev_close,
        paragraph_4_token=STANDARD_TOKEN,
        top_signal_plain_english=top_signal,
        domestic_override=override,
    )
