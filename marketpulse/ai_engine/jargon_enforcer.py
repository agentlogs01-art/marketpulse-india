"""
ai_engine/jargon_enforcer.py

FR-02.4.1 — Mandatory Inline Jargon Definition Rule.

Layer 1: the LLM is instructed (system prompt) to define jargon inline on
first use. Layer 2 (this module): a deterministic Python post-processing
pass that scans the LLM's plain-English text fields, finds any jargon-
registry term used WITHOUT an inline definition, and injects the
canonical definition immediately after the term's first occurrence.

This is intentionally pure-Python / regex — no LLM re-prompt loop, to
avoid burning through the Gemini 1.5 Flash free-tier 15 RPM limit during
the 06:45-06:50 IST critical assembly window (PRD Section 3 budget note).
"""

from __future__ import annotations

import re

from marketpulse.constants.jargon_registry import JARGON_REGISTRY, JargonTerm


def _build_term_pattern(term: JargonTerm) -> re.Pattern:
    """Word-boundary, case-insensitive pattern matching any alias form."""
    forms = sorted(term.all_forms(), key=len, reverse=True)
    escaped = [re.escape(f) for f in forms]
    pattern = r"\b(" + "|".join(escaped) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


# A term counts as "already defined inline" if it's immediately followed by
# a parenthetical, or by an em-dash / en-dash explanation, within ~80 chars.
_DEFINITION_FOLLOWUP = re.compile(r"^\s*(\(|\u2014|\u2013|-\s|, meaning|, which means)")


def has_inline_definition(text: str, match_end: int) -> bool:
    tail = text[match_end:match_end + 90]
    return bool(_DEFINITION_FOLLOWUP.match(tail))


def enforce_jargon_definitions(text: str) -> tuple[str, list[dict]]:
    """
    Scan `text` for jargon-registry terms lacking an inline definition and
    inject the canonical definition after the FIRST occurrence only
    (subsequent occurrences in the same text are left as-is, since the
    reader has already seen the definition).

    Returns (modified_text, injections) where injections is a list of dicts
    suitable for PipelineRunRecord.jargon_injections (for QA/audit logging).
    """
    injections: list[dict] = []
    already_defined_in_text: set[str] = set()

    for term in JARGON_REGISTRY:
        pattern = _build_term_pattern(term)
        match = pattern.search(text)
        if not match:
            continue

        canonical_key = term.canonical.lower()
        if canonical_key in already_defined_in_text:
            continue

        if has_inline_definition(text, match.end()):
            # LLM already defined it inline (Layer 1 worked) — nothing to do.
            already_defined_in_text.add(canonical_key)
            continue

        # Inject definition right after the matched term.
        insertion = f" ({term.definition})"
        text = text[:match.end()] + insertion + text[match.end():]
        already_defined_in_text.add(canonical_key)

        injections.append({
            "term": term.canonical,
            "matched_text": match.group(0),
            "definition_injected": term.definition,
            "position": match.start(),
        })

    return text, injections


def enforce_jargon_on_fields(fields: dict, field_names: list[str]) -> tuple[dict, list[dict]]:
    """Apply enforce_jargon_definitions across multiple narrative fields."""
    all_injections: list[dict] = []
    out = dict(fields)
    for name in field_names:
        if name in out and isinstance(out[name], str):
            new_text, injections = enforce_jargon_definitions(out[name])
            out[name] = new_text
            for inj in injections:
                inj["field"] = name
            all_injections.extend(injections)
    return out, all_injections
