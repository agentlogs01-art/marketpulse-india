"""
tests/test_dispatcher.py

Tests delivery/dispatcher.py's flatten_results_for_audit -- the one pure,
easily-unit-testable piece of the dispatcher (the per-channel send
functions themselves require network/Supabase and are exercised by hand
against real credentials, same posture as the other live-network modules
in this project).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.delivery.dispatcher import flatten_results_for_audit


class TestFlattenResultsForAudit(unittest.TestCase):
    def test_flattens_sent_across_channels(self):
        results = {
            "email": {"sent": ["a@x.com", "b@x.com"], "failed": [], "total": 2},
            "whatsapp": {"sent": ["+919876543210"], "failed": [], "total": 1},
            "telegram": None,
        }
        sent, failed = flatten_results_for_audit(results)
        self.assertEqual(len(sent), 3)
        self.assertEqual(failed, [])
        channels = {s["channel"] for s in sent}
        self.assertEqual(channels, {"email", "whatsapp"})

    def test_flattens_failed_with_error_and_channel(self):
        results = {
            "email": {"sent": [], "failed": [{"address": "a@x.com", "error": "bounced"}], "total": 1},
            "whatsapp": None,
            "telegram": None,
        }
        sent, failed = flatten_results_for_audit(results)
        self.assertEqual(sent, [])
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["channel"], "email")
        self.assertEqual(failed[0]["error"], "bounced")

    def test_skips_none_channels_entirely(self):
        results = {"email": None, "whatsapp": None, "telegram": None}
        sent, failed = flatten_results_for_audit(results)
        self.assertEqual(sent, [])
        self.assertEqual(failed, [])

    def test_all_three_channels_combine(self):
        results = {
            "email": {"sent": ["a@x.com"], "failed": [], "total": 1},
            "whatsapp": {"sent": ["+91123"], "failed": [{"address": "+91456", "error": "no session"}], "total": 2},
            "telegram": {"sent": ["555111"], "failed": [], "total": 1},
        }
        sent, failed = flatten_results_for_audit(results)
        self.assertEqual(len(sent), 3)
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["channel"], "whatsapp")


if __name__ == "__main__":
    unittest.main()
