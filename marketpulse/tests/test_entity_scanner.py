"""
tests/test_entity_scanner.py

FR-02.4.2 -- SEBI Entity Genericisation Rule, Layer 2 enforcement.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.ai_engine.entity_scanner import scan_and_genericize, should_suppress_run


class TestEntityScanner(unittest.TestCase):
    def test_replaces_named_bank(self):
        text = "HDFC Bank shares may react to the rate decision."
        result, violations = scan_and_genericize(text)
        self.assertNotIn("HDFC Bank", result)
        self.assertIn("Major private-sector Indian banks", result)
        self.assertEqual(len(violations), 1)

    def test_replaces_it_company_case_insensitive(self):
        text = "infosys and TCS could see order book pressure."
        result, violations = scan_and_genericize(text)
        self.assertEqual(len(violations), 2)
        self.assertNotIn("TCS", result)

    def test_no_entity_present_returns_unchanged(self):
        text = "The IT sector may see modest pressure from a stronger dollar."
        result, violations = scan_and_genericize(text)
        self.assertEqual(result, text)
        self.assertEqual(violations, [])

    def test_suppression_threshold(self):
        violations = [
            {"matched_entity": e, "replacement": "x", "position": 0}
            for e in ["tcs", "infosys", "wipro", "hcl technologies"]
        ]
        self.assertTrue(should_suppress_run(violations))

    def test_below_suppression_threshold(self):
        violations = [
            {"matched_entity": e, "replacement": "x", "position": 0}
            for e in ["tcs", "infosys"]
        ]
        self.assertFalse(should_suppress_run(violations))


if __name__ == "__main__":
    unittest.main()
