"""
constants/jargon_registry.py

FR-02.4.1 — Mandatory Inline Jargon Definition Rule.

This is the living "Jargon Term Registry" seed list from the PRD (Section
2 FR-02.4.1 + Appendix A Glossary). Every term here must define its
`term_aliases` to support abbreviation/plural matching at word boundaries
(e.g. "basis points" must also match "bps" and "bp").

The registry is consumed by ai_engine/jargon_enforcer.py, which performs
the Layer 2 deterministic Python post-processing injection. No LLM
re-prompt loop exists for jargon remediation (explicitly removed in PRD
to avoid Gemini 15 RPM rate-limit risk).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JargonTerm:
    canonical: str                 # canonical display form, e.g. "FII"
    definition: str                # plain-English definition (no parens)
    term_aliases: tuple = field(default_factory=tuple)  # e.g. ("FIIs",)

    def all_forms(self) -> tuple:
        return (self.canonical,) + self.term_aliases


# Seed list — must mirror Appendix A Glossary exactly so the glossary stays
# the authoritative source per the PRD's MVP Scope Note on Appendix A.
JARGON_REGISTRY: list[JargonTerm] = [
    JargonTerm(
        "Hawkish",
        "signalling a preference for keeping interest rates high to fight inflation",
        ("hawkish",),
    ),
    JargonTerm(
        "Dovish",
        "signalling a preference for cutting interest rates to boost economic growth",
        ("dovish",),
    ),
    JargonTerm(
        "Basis points",
        "a unit for measuring interest rate changes; 100 bps = 1%",
        ("bps", "bp", "basis point"),
    ),
    JargonTerm(
        "Yield curve",
        "a chart showing interest rates on government bonds across different time periods",
        ("yield curves",),
    ),
    JargonTerm(
        "Inverted yield curve",
        "when short-term bonds pay more interest than long-term ones, often a warning sign",
        ("inverted yield curves",),
    ),
    JargonTerm(
        "FII",
        "Foreign Institutional Investors \u2014 large overseas funds that buy and sell Indian stocks",
        ("FIIs",),
    ),
    JargonTerm(
        "DII",
        "Domestic Institutional Investors \u2014 Indian mutual funds and insurance companies",
        ("DIIs",),
    ),
    JargonTerm(
        "FOMC",
        "Federal Open Market Committee \u2014 the US Fed's committee that decides interest rates",
        (),
    ),
    JargonTerm(
        "Repo Rate",
        "the interest rate at which RBI lends money to Indian banks overnight",
        ("repo rates",),
    ),
    JargonTerm(
        "CAD",
        "Current Account Deficit \u2014 when India spends more on imports than it earns from exports",
        (),
    ),
    JargonTerm(
        "Gap up",
        "when the stock market opens meaningfully higher than it closed the previous day",
        ("gap ups",),
    ),
    JargonTerm(
        "Gap down",
        "when the stock market opens meaningfully lower than it closed the previous day",
        ("gap downs",),
    ),
    JargonTerm(
        "Sentiment",
        "the overall mood or attitude of investors \u2014 whether they feel optimistic or pessimistic",
        (),
    ),
    JargonTerm(
        "Macro",
        "short for macroeconomics \u2014 the study of big-picture economic forces like inflation, GDP, and interest rates",
        (),
    ),
    JargonTerm(
        "PMI",
        "Purchasing Managers' Index \u2014 a monthly survey that measures whether businesses are growing or shrinking",
        (),
    ),
    JargonTerm(
        "Brent crude",
        "the global benchmark price of oil per barrel; rising crude increases India's import bill and can weaken the rupee",
        ("brent", "crude oil"),
    ),
    JargonTerm(
        "GIFT Nifty",
        "a futures contract on the Nifty 50 index traded at GIFT City, India from 06:30 AM IST \u2014 used as an early indicator of how Indian markets will open",
        (),
    ),
]


def find_term(text_token: str) -> JargonTerm | None:
    """Case-insensitive lookup of a registry term by canonical name or alias."""
    lowered = text_token.lower()
    for term in JARGON_REGISTRY:
        if lowered in (f.lower() for f in term.all_forms()):
            return term
    return None
