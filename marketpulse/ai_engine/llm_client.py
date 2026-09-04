"""
ai_engine/llm_client.py

FR-02.2 — AI Sentiment & Sector Impact Analysis.

Wraps Google Gemini 1.5 Flash (free tier, per PRD Section 3 infra budget:
$0/mo for the LLM call itself, only egress/compute cost on Railway). The
prompt below:
  - Restricts sectors to exactly the 5 MVP sectors (FR-02.2 sector
    reduction).
  - Embeds the SEBI ENTITY_RULE_SYSTEM_PROMPT (Layer 1 entity defense).
  - Requests strict JSON output matching EventAnalysis schema, so the
    parser can validate without an LLM round-trip retry loop.

No API key is hardcoded; read from environment (GEMINI_API_KEY) per
12-factor config and the PRD's emphasis on Railway env-var secrets.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional
import logging
import time
import requests

from marketpulse.constants.sebi_entity_rules import ENTITY_RULE_SYSTEM_PROMPT
from marketpulse.models.schemas import (
    BiasLabel,
    Direction,
    EventAnalysis,
    NewsEvent,
    Sector,
    SectorImpact,
    Sentiment,
)

GEMINI_MODEL = "gemini-2.5-flash"  # Or your chosen model identifier
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

MVP_SECTORS = [s.value for s in Sector]

SYSTEM_PROMPT = f"""\
You are a financial analyst producing pre-market briefings for first-time
Indian retail investors with NO finance background. Plain English only.

{ENTITY_RULE_SYSTEM_PROMPT}

SECTOR SCOPE: You may only reference these five sectors, exactly as named:
{", ".join(MVP_SECTORS)}. Do not invent additional sectors. If an event
does not clearly affect any of these five, return an empty
affected_sectors list for it.

OUTPUT FORMAT: Return ONLY valid JSON matching this exact schema, with no
markdown code fences, no preamble, no explanation outside the JSON:

{{
  "overall_sentiment": "BULLISH" | "BEARISH" | "NEUTRAL" | "MIXED",
  "sentiment_intensity": <integer 1-5>,
  "confidence": <float 0.0-1.0>,
  "affected_sectors": [
    {{
      "sector": "BANKING" | "IT" | "AUTO" | "ENERGY" | "FMCG",
      "direction": "POSITIVE" | "NEGATIVE" | "NEUTRAL",
      "impact_magnitude": <integer 1-5>,
      "rationale_plain_english": "<max 60 words, sector-level only, no entity names>"
    }}
  ],
  "nifty50_overall_bias": "GAP_UP_STRONG" | "GAP_UP_MILD" | "FLAT" | "GAP_DOWN_MILD" | "GAP_DOWN_STRONG",
  "one_line_summary_for_beginner": "<max 25 words, plain English>"
}}
"""


def _build_user_prompt(event: NewsEvent, market_context: str = "") -> str:
    published = event.published_at or "unknown"
    context_block = f"{market_context.strip()}\n\n" if market_context.strip() else ""
    return (
        f"{context_block}"
        f"Headline: {event.headline}\n"
        f"Summary: {event.body_summary}\n"
        f"Event type: {event.event_type.value}\n"
        f"Geographic origin: {event.geographic_origin.value}\n"
        f"Published at: {published}\n"
        f"Source: {event.source}\n"
        f"Source credibility score: {event.credibility_score}\n\n"
        "Analyze this overnight news event's likely impact on Indian equity "
        "markets at the open, per the JSON schema in your system instructions. "
        "Use the snapshot only as context; do not invent prices."
    )


def _extract_json(raw_text: str) -> dict:
    text = raw_text.strip()
    
    # 1. Remove markdown code fences if present (e.g. ```json ... ```)
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    
    # 2. Extract first `{` to last `}` boundary
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    
    if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
        text = text[start_idx:end_idx + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Log snippet instead of full text to prevent giant log outputs on fail
        snippet = raw_text[:200] + "..." if len(raw_text) > 200 else raw_text
        raise ValueError(f"Failed to parse LLM response as JSON. Snippet: {snippet}") from e


def call_gemini(system_prompt: str, user_prompt: str, api_key: Optional[str] = None) -> str:
    """
    HTTP call to Gemini API with exponential retries and relaxed timeout settings
    to prevent pipeline crashes on large prompts or transient API slowness.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set in environment")

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    }

    # (Connect timeout, Read timeout)
    # 5 seconds to establish connection, 60 seconds to process & stream response
    timeout_config = (5, 60)
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                GEMINI_API_URL,
                params={"key": key},
                json=payload,
                timeout=timeout_config,
            )
            resp.raise_for_status()
            data = resp.json()

            # Safely extract text from candidate payload
            candidate = data["candidates"][0]
            text_response = candidate["content"]["parts"][0]["text"]
            return text_response

        except (requests.exceptions.Timeout, requests.exceptions.HTTPError) as exc:
            if attempt == max_retries:
                logger.error("Gemini API call failed after %d attempts: %s", max_retries, exc)
                raise exc

            sleep_time = attempt * 2  # Exponential backoff (2s, 4s)
            logger.warning("Gemini API call failed (attempt %d/%d): %s. Retrying in %ds...", attempt, max_retries, exc, sleep_time)
            time.sleep(sleep_time)

def analyze_event(
    event: NewsEvent,
    api_key: Optional[str] = None,
    market_context: str = "",
) -> EventAnalysis:
    """
    Run FR-02.2 sentiment + sector impact analysis on a single NewsEvent.
    Returns a populated EventAnalysis. Raises on malformed LLM output so
    the orchestrator can decide whether to retry, skip the event, or fall
    back to a neutral/default analysis.
    """

    raw = call_gemini(
        SYSTEM_PROMPT,
        _build_user_prompt(event, market_context=market_context),
        api_key=api_key,
    )
    parsed = _extract_json(raw)

    affected = [
        SectorImpact(
            sector=Sector(s["sector"]),
            direction=Direction(s["direction"]),
            impact_magnitude=int(s["impact_magnitude"]),
            rationale_plain_english=s["rationale_plain_english"],
        )
        for s in parsed.get("affected_sectors", [])
        if s.get("sector") in MVP_SECTORS
    ]

    analysis = EventAnalysis(
        event_id=event.event_id,
        overall_sentiment=Sentiment(parsed["overall_sentiment"]),
        sentiment_intensity=int(parsed["sentiment_intensity"]),
        confidence=float(parsed["confidence"]),
        affected_sectors=affected,
        nifty50_overall_bias=BiasLabel(parsed["nifty50_overall_bias"]),
        one_line_summary_for_beginner=parsed["one_line_summary_for_beginner"],
    )

    # Carry sentiment_intensity back onto the source event — used by
    # FR-02.6 domestic-override trigger logic downstream.
    event.sentiment_intensity = analysis.sentiment_intensity

    return analysis


def fallback_neutral_analysis(event: NewsEvent) -> EventAnalysis:
    """
    Used when the LLM call fails or times out. Per pipeline resilience
    requirements, a neutral/no-impact analysis is safer than crashing the
    06:45-06:50 IST critical window or sending a stale/broken email.
    """
    return EventAnalysis(
        event_id=event.event_id,
        overall_sentiment=Sentiment.NEUTRAL,
        sentiment_intensity=1,
        confidence=0.0,
        affected_sectors=[],
        nifty50_overall_bias=BiasLabel.FLAT,
        one_line_summary_for_beginner="This event's market impact could not be analyzed in time.",
    )
