"""
tests/test_jargon_enforcer.py

FR-02.4.1 -- Mandatory Inline Jargon Definition Rule, Layer 2 enforcement.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.ai_engine.jargon_enforcer import enforce_jargon_definitions


class TestJargonEnforcer(unittest.TestCase):
    def test_injects_definition_when_missing(self):
        text = "The Fed turned hawkish on rate policy."
        result, injections = enforce_jargon_definitions(text)
        self.assertIn("signalling a preference for keeping interest rates high", result)
        self.assertEqual(len(injections), 1)
        self.assertEqual(injections[0]["term"], "Hawkish")

    def test_skips_injection_if_already_defined_inline(self):
        text = "The Fed turned hawkish (meaning it favors higher rates) today."
        result, injections = enforce_jargon_definitions(text)
        self.assertEqual(result, text)
        self.assertEqual(len(injections), 0)

    def test_matches_alias_forms(self):
        text = "FIIs sold heavily in the cash market."
        result, injections = enforce_jargon_definitions(text)
        self.assertEqual(len(injections), 1)
        self.assertIn("Foreign Institutional Investors", result)

    def test_only_defines_first_occurrence(self):
        text = "Rates rose 25 bps. Later, another 25 bps hike followed."
        result, injections = enforce_jargon_definitions(text)
        self.assertEqual(len(injections), 1)
        # Second "bps" occurrence should remain undecorated.
        self.assertEqual(result.count("a unit for measuring interest rate changes"), 1)

    def test_no_jargon_present_returns_unchanged_text(self):
        text = "Markets are expected to open flat today."
        result, injections = enforce_jargon_definitions(text)
        self.assertEqual(result, text)
        self.assertEqual(injections, [])


if __name__ == "__main__":
    unittest.main()
