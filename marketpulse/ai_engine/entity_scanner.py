"""
ai_engine/entity_scanner.py

FR-02.4.2 — SEBI Entity Genericisation Rule, Layer 2.

Layer 1 is the LLM system prompt (constants/sebi_entity_rules.py
ENTITY_RULE_SYSTEM_PROMPT). Layer 2, implemented here, is a deterministic
regex post-processing scan + auto-replace pass that runs on every
narrative field before assembly. Any named entity caught is logged as a
PipelineRunRecord.entity_violations entry for audit, and the text is
auto-corrected via the conversion matrix.

If more than MAX_ENTITY_VIOLATIONS_BEFORE_SUPPRESSION distinct violations
are found in a single run, the run is flagged for suppression (FR-02.4.2
point 3) — better to send no email than a non-compliant one.
"""

from __future__ import annotations

import re

from marketpulse.constants.sebi_entity_rules import (
    MAX_ENTITY_VIOLATIONS_BEFORE_SUPPRESSION,
    get_blacklist_terms,
    get_replacement,
)

_BLACKLIST_TERMS = get_blacklist_terms()
_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _BLACKLIST_TERMS) + r")\b",
    re.IGNORECASE,
)


def scan_and_genericize(text: str) -> tuple[str, list[dict]]:
    """
    Find and replace any blacklisted named entity in `text` with its
    generic sector descriptor. Returns (clean_text, violations).
    """
    violations: list[dict] = []

    def _replace(match: re.Match) -> str:
        original = match.group(0)
        replacement = get_replacement(original.lower())
        violations.append({
            "matched_entity": original,
            "replacement": replacement,
            "position": match.start(),
        })
        return replacement

    clean_text = _PATTERN.sub(_replace, text)
    return clean_text, violations


def scan_fields(fields: dict, field_names: list[str]) -> tuple[dict, list[dict]]:
    """Apply scan_and_genericize across multiple narrative fields."""
    all_violations: list[dict] = []
    out = dict(fields)
    for name in field_names:
        if name in out and isinstance(out[name], str):
            clean_text, violations = scan_and_genericize(out[name])
            out[name] = clean_text
            for v in violations:
                v["field"] = name
            all_violations.extend(violations)
    return out, all_violations


def should_suppress_run(violations: list[dict]) -> bool:
    """
    FR-02.4.2 point 3: if entity leakage is severe/frequent enough, it's
    safer to suppress the send entirely than risk a compliance breach that
    auto-replacement might not have fully neutralized (e.g. overlapping
    matches, partial brand names in headlines).
    """
    distinct_entities = {v["matched_entity"].lower() for v in violations}
    return len(distinct_entities) > MAX_ENTITY_VIOLATIONS_BEFORE_SUPPRESSION
