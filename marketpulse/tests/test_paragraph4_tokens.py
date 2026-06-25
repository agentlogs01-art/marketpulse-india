"""
tests/test_paragraph4_tokens.py

FR-02.5 sentinel token resolution must be 100% deterministic and require
zero LLM/network calls -- these tests assert exactly that.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.constants.paragraph4_tokens import (
    FLAT_OVERRIDE_RESOLUTION,
    FLAT_OVERRIDE_TOKEN,
    STANDARD_TOKEN,
    build_divergence_token,
    parse_divergence_token,
    resolve_paragraph_4,
)


class TestParagraph4Tokens(unittest.TestCase):
    def test_flat_override_resolves_to_fixed_text(self):
        result = resolve_paragraph_4(FLAT_OVERRIDE_TOKEN)
        self.assertEqual(result, FLAT_OVERRIDE_RESOLUTION)

    def test_standard_token_uses_template(self):
        result = resolve_paragraph_4(
            STANDARD_TOKEN,
            bias_label_plain="open higher",
            top_signal_plain_english="strong US jobs data",
        )
        self.assertIn("strong US jobs data", result)

    def test_divergence_token_round_trip(self):
        token = build_divergence_token("higher", "weak US jobs data", "conflicting")
        fields = parse_divergence_token(token)
        self.assertEqual(fields["direction"], "higher")
        self.assertEqual(fields["event"], "weak US jobs data")
        self.assertEqual(fields["signal"], "conflicting")

    def test_divergence_token_resolves_with_interpolated_fields(self):
        token = build_divergence_token("lower", "a surprise rate hike", "opposing")
        result = resolve_paragraph_4(token)
        self.assertIn("lower", result)
        self.assertIn("a surprise rate hike", result)
        self.assertIn("opposing", result)

    def test_divergence_token_rejects_malformed_input(self):
        with self.assertRaises(ValueError):
            parse_divergence_token("not_a_divergence_token")


if __name__ == "__main__":
    unittest.main()
