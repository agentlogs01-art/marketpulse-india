"""
tests/test_session_repo.py

Direct tests for persistence/session_repo.py against the FakeSupabaseClient,
covering issuance, resolution, expiry, and revocation independent of the
higher-level api.handlers flows that already exercise this indirectly.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.persistence import session_repo
from marketpulse.tests.test_persistence import FakeSupabaseClient


class TestSessionRepo(unittest.TestCase):
    def setUp(self):
        self.client = FakeSupabaseClient()

    def test_create_session_returns_a_token(self):
        token = session_repo.create_session("sub-1", client=self.client)
        self.assertTrue(token)
        rows = self.client.select(session_repo.TABLE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["subscriber_id"], "sub-1")

    def test_resolves_valid_token_to_subscriber_id(self):
        token = session_repo.create_session("sub-2", client=self.client)
        resolved = session_repo.get_subscriber_id_for_token(token, client=self.client)
        self.assertEqual(resolved, "sub-2")

    def test_unknown_token_resolves_to_none(self):
        resolved = session_repo.get_subscriber_id_for_token("does-not-exist", client=self.client)
        self.assertIsNone(resolved)

    def test_empty_token_resolves_to_none(self):
        resolved = session_repo.get_subscriber_id_for_token("", client=self.client)
        self.assertIsNone(resolved)

    def test_revoked_session_no_longer_resolves(self):
        token = session_repo.create_session("sub-3", client=self.client)
        session_repo.revoke_session(token, client=self.client)
        resolved = session_repo.get_subscriber_id_for_token(token, client=self.client)
        self.assertIsNone(resolved)

    def test_expired_session_no_longer_resolves(self):
        token = session_repo.create_session("sub-4", client=self.client)
        rows = self.client.select(session_repo.TABLE)
        # Force the session into the past to simulate expiry.
        expired_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.client.update(
            session_repo.TABLE, params={"token": f"eq.{token}"}, patch={"expires_at": expired_at}
        )
        resolved = session_repo.get_subscriber_id_for_token(token, client=self.client)
        self.assertIsNone(resolved)

    def test_revoke_all_sessions_for_subscriber(self):
        token1 = session_repo.create_session("sub-5", client=self.client)
        token2 = session_repo.create_session("sub-5", client=self.client)
        session_repo.revoke_all_sessions_for_subscriber("sub-5", client=self.client)
        self.assertIsNone(session_repo.get_subscriber_id_for_token(token1, client=self.client))
        self.assertIsNone(session_repo.get_subscriber_id_for_token(token2, client=self.client))

    def test_revoke_all_does_not_affect_other_subscribers(self):
        token_a = session_repo.create_session("sub-a", client=self.client)
        token_b = session_repo.create_session("sub-b", client=self.client)
        session_repo.revoke_all_sessions_for_subscriber("sub-a", client=self.client)
        self.assertIsNone(session_repo.get_subscriber_id_for_token(token_a, client=self.client))
        self.assertEqual(session_repo.get_subscriber_id_for_token(token_b, client=self.client), "sub-b")


if __name__ == "__main__":
    unittest.main()
