"""
constants/sebi_entity_rules.py

FR-02.4.2 — SEBI Entity Genericisation Rule (hard compliance requirement,
permanent status). No individual company name, brand name, or stock
ticker may appear anywhere in generated output. This module defines:

  1. The absolute blacklist of named entities (extend at implementation;
     PRD explicitly calls this list non-exhaustive).
  2. The mandatory conversion matrix mapping entity -> generic sector
     descriptor.
  3. The LLM system-prompt instruction block (Layer 1), written WITHOUT
     named entity examples per the v1.6 prompt-design rationale (naming
     entities, even as negative examples, increases leakage risk).

Layer 2 (post-processing regex entity scan) lives in
ai_engine/entity_scanner.py and imports the blacklist/matrix from here.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Mandatory Conversion Matrix (entity -> generic sector descriptor)
# Keys are matched case-insensitively against the blacklist below.
# ---------------------------------------------------------------------------

CONVERSION_MATRIX: dict[str, str] = {
    # IT / Technology services
    "tcs": "Large Indian technology services companies",
    "tata consultancy services": "Large Indian technology services companies",
    "infosys": "Large Indian technology services companies",
    "infy": "Large Indian technology services companies",
    "wipro": "Large Indian technology services companies",
    "hcl technologies": "Large Indian technology services companies",
    "hcl tech": "Large Indian technology services companies",
    "tech mahindra": "Large Indian technology services companies",

    # Private-sector banks
    "hdfc bank": "Major private-sector Indian banks",
    "icici bank": "Major private-sector Indian banks",
    "kotak mahindra bank": "Major private-sector Indian banks",
    "kotak": "Major private-sector Indian banks",
    "axis bank": "Major private-sector Indian banks",

    # Public-sector banks
    "sbi": "Large public-sector Indian banks",
    "state bank of india": "Large public-sector Indian banks",
    "bank of baroda": "Large public-sector Indian banks",
    "punjab national bank": "Large public-sector Indian banks",

    # Energy / conglomerate
    "reliance industries": "Domestic energy and conglomerate companies",
    "reliance": "Domestic energy and conglomerate companies",
    "ril": "Domestic energy and conglomerate companies",
    "ongc": "Public-sector energy producers",
    "ntpc": "Public-sector energy producers",
    "power grid": "Public-sector energy producers",

    # Auto
    "maruti suzuki": "Indian automobile manufacturers",
    "maruti": "Indian automobile manufacturers",
    "tata motors": "Indian automobile manufacturers",
    "mahindra & mahindra": "Indian automobile manufacturers",
    "mahindra and mahindra": "Indian automobile manufacturers",
    "bajaj auto": "Indian automobile manufacturers",

    # FMCG / consumer goods
    "hul": "Indian consumer goods companies",
    "hindustan unilever": "Indian consumer goods companies",
    "itc": "Indian consumer goods companies",
    "nestle india": "Indian consumer goods companies",
    "dabur": "Indian consumer goods companies",
    "marico": "Indian consumer goods companies",

    # Brokerage platforms (mentioned in blacklist, not a market sector —
    # generic catch-all to avoid implying endorsement of a specific platform)
    "groww": "popular Indian retail investing platforms",
    "zerodha": "popular Indian retail investing platforms",
    "upstox": "popular Indian retail investing platforms",
}

# Absolute Blacklist — PRD: "non-exhaustive — engineering must extend this
# list at implementation." Anything in CONVERSION_MATRIX is automatically
# part of the blacklist; this set adds bare tickers / variants not covered
# by a natural-language key above.
ADDITIONAL_BLACKLIST_TOKENS: set[str] = {
    "tcs", "infy", "ril",
}


def get_blacklist_terms() -> list[str]:
    """All entity strings to scan for, longest first (for greedy regex match)."""
    terms = set(CONVERSION_MATRIX.keys()) | ADDITIONAL_BLACKLIST_TOKENS
    return sorted(terms, key=len, reverse=True)


def get_replacement(entity_lower: str) -> str:
    return CONVERSION_MATRIX.get(
        entity_lower, "the relevant Indian companies in this sector"
    )


# ---------------------------------------------------------------------------
# Layer 1 — LLM System Prompt Instruction Block (verbatim from PRD v1.6)
# No named entities appear here by design (v1.6 prompt-hardening rationale).
# ---------------------------------------------------------------------------

ENTITY_RULE_SYSTEM_PROMPT = """\
ENTITY RULE (MANDATORY, NON-NEGOTIABLE): You must NEVER write the name of any
individual Indian or global publicly listed company, brand, or stock ticker in
your output. This is a strict regulatory compliance requirement.

All analysis must be expressed at the sector level only. When a macro event
affects a sector, name the sector and describe the mechanism - do not name
any company within that sector.

Permitted sector descriptors:
  IT sector        -> "Large Indian technology services companies"
  Banking sector   -> "Major private-sector Indian banks" or
                     "Large public-sector Indian banks"
  Energy sector    -> "Domestic energy producers" or
                     "Public-sector energy companies"
  Auto sector      -> "Indian automobile manufacturers"
  FMCG sector      -> "Indian consumer goods companies"

Any company name, brand name, or ticker symbol in your output is an
automatic validation failure. Write only macro-to-sector impact chains.
"""

# Max entity violations tolerated in a single run before suppression
# (FR-02.4.2 Layer 2, point 3).
MAX_ENTITY_VIOLATIONS_BEFORE_SUPPRESSION = 3
