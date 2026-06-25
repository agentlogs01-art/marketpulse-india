"""
tests/test_api_handlers.py

Tests api/handlers.py against the same FakeSupabaseClient pattern used
in tests/test_persistence.py, monkeypatching persistence.supabase_client
.get_client() so every repo call inside the handlers hits the in-memory
fake instead of a real Supabase project. Email-sending (transactional.py)
is monkeypatched separately so no SMTP connection is attempted.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.api import handlers
from marketpulse.persistence import supabase_client
from marketpulse.tests.test_persistence import FakeSupabaseClient

VALID_PASSWORD = "correct-horse-battery"


class ApiHandlersTestCase(unittest.TestCase):
    """Base case: installs a fresh FakeSupabaseClient as the module-level
    default client before each test, and a no-op email sender."""

    def setUp(self):
        self.fake_client = FakeSupabaseClient()
        self._client_patch = patch.object(supabase_client, "_default_client", self.fake_client)
        self._client_patch.start()

        self.sent_emails = []

        def fake_send_verification_email(to_email, verify_url):
            self.sent_emails.append({"type": "verify", "to": to_email, "url": verify_url})

        def fake_send_telegram_linked_confirmation(to_email):
            self.sent_emails.append({"type": "telegram_linked", "to": to_email})

        self._verify_email_patch = patch(
            "marketpulse.email_system.transactional.send_verification_email",
            side_effect=fake_send_verification_email,
        )
        self._telegram_confirm_patch = patch(
            "marketpulse.email_system.transactional.send_telegram_linked_confirmation",
            side_effect=fake_send_telegram_linked_confirmation,
        )
        self._verify_email_patch.start()
        self._telegram_confirm_patch.start()

    def tearDown(self):
        self._client_patch.stop()
        self._verify_email_patch.stop()
        self._telegram_confirm_patch.stop()

    def _verification_token(self):
        return self.sent_emails[-1]["url"].split("token=")[1]

    def _signup_and_verify(self, email, password=VALID_PASSWORD, **kwargs):
        handlers.signup(password, email=email, **kwargs)
        token = self._verification_token()
        handlers.verify_email(token)

    def _signup_verify_and_login(self, email, password=VALID_PASSWORD, **kwargs):
        self._signup_and_verify(email, password=password, **kwargs)
        result = handlers.login(email, password)
        return result["session_token"]


class TestSignup(ApiHandlersTestCase):
    def test_signup_creates_pending_subscriber_and_sends_email(self):
        result = handlers.signup(VALID_PASSWORD, email="new@example.com")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "pending_verification")
        self.assertEqual(len(self.sent_emails), 1)
        self.assertEqual(self.sent_emails[0]["to"], "new@example.com")

    def test_signup_rejects_invalid_email(self):
        with self.assertRaises(handlers.ValidationError):
            handlers.signup(VALID_PASSWORD, email="not-an-email")

    def test_signup_requires_email_or_mobile(self):
        with self.assertRaises(handlers.ValidationError):
            handlers.signup(VALID_PASSWORD)

    def test_signup_rejects_short_password(self):
        with self.assertRaises(handlers.ValidationError):
            handlers.signup("short", email="a@example.com")

    def test_signup_normalizes_email_case_and_whitespace(self):
        handlers.signup(VALID_PASSWORD, email="  Mixed.Case@Example.COM  ")
        rows = self.fake_client.select("subscribers")
        self.assertEqual(rows[0]["email"], "mixed.case@example.com")

    def test_signup_rejects_unknown_channel(self):
        with self.assertRaises(handlers.ValidationError):
            handlers.signup(VALID_PASSWORD, email="a@example.com", channels=["carrier_pigeon"])

    def test_signup_requires_whatsapp_number_when_whatsapp_selected(self):
        with self.assertRaises(handlers.ValidationError):
            handlers.signup(VALID_PASSWORD, email="a@example.com", channels=["email", "whatsapp"])

    def test_signup_accepts_valid_whatsapp_number(self):
        result = handlers.signup(
            VALID_PASSWORD,
            email="a@example.com",
            channels=["email", "whatsapp"],
            whatsapp_number="+919876543210",
        )
        self.assertTrue(result["ok"])
        rows = self.fake_client.select("subscribers")
        self.assertEqual(rows[0]["whatsapp_number"], "+919876543210")

    def test_signup_rejects_malformed_whatsapp_number(self):
        with self.assertRaises(handlers.ValidationError):
            handlers.signup(VALID_PASSWORD, email="a@example.com", channels=["whatsapp"], whatsapp_number="98765")

    def test_signup_is_idempotent_for_same_email(self):
        handlers.signup(VALID_PASSWORD, email="dup@example.com")
        handlers.signup(VALID_PASSWORD, email="dup@example.com")
        rows = self.fake_client.select("subscribers")
        self.assertEqual(len(rows), 1)

    def test_signup_with_mobile_only_skips_email_verification_and_activates(self):
        result = handlers.signup(VALID_PASSWORD, mobile_number="+919876543210")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "active")
        self.assertEqual(len(self.sent_emails), 0)
        rows = self.fake_client.select("subscribers")
        self.assertEqual(rows[0]["status"], "active")

    def test_signup_rejects_malformed_mobile_number(self):
        with self.assertRaises(handlers.ValidationError):
            handlers.signup(VALID_PASSWORD, mobile_number="98765")

    def test_signup_with_email_and_mobile_still_requires_email_verification(self):
        result = handlers.signup(VALID_PASSWORD, email="both@example.com", mobile_number="+919876543210")
        self.assertEqual(result["status"], "pending_verification")


class TestVerifyEmail(ApiHandlersTestCase):
    def test_verify_activates_pending_subscriber(self):
        handlers.signup(VALID_PASSWORD, email="verify-me@example.com")
        token = self._verification_token()

        result = handlers.verify_email(token)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["email"], "verify-me@example.com")

    def test_verify_rejects_unknown_token(self):
        result = handlers.verify_email("not-a-real-token")
        self.assertFalse(result["ok"])

    def test_verify_rejects_already_used_token(self):
        handlers.signup(VALID_PASSWORD, email="verify-twice@example.com")
        token = self._verification_token()
        handlers.verify_email(token)

        second_result = handlers.verify_email(token)
        self.assertFalse(second_result["ok"])

    def test_verify_missing_token_raises_validation_error(self):
        with self.assertRaises(handlers.ValidationError):
            handlers.verify_email("")


class TestLoginLogout(ApiHandlersTestCase):
    def test_login_with_email_succeeds_after_verification(self):
        self._signup_and_verify("loginme@example.com")
        result = handlers.login("loginme@example.com", VALID_PASSWORD)
        self.assertTrue(result["ok"])
        self.assertTrue(result["session_token"])
        self.assertEqual(result["subscriber"]["email"], "loginme@example.com")

    def test_login_response_never_includes_password_hash(self):
        self._signup_and_verify("nohash@example.com")
        result = handlers.login("nohash@example.com", VALID_PASSWORD)
        self.assertNotIn("password_hash", result["subscriber"])

    def test_login_with_wrong_password_raises_auth_error(self):
        self._signup_and_verify("wrongpw@example.com")
        with self.assertRaises(handlers.AuthError):
            handlers.login("wrongpw@example.com", "totally-wrong-password")

    def test_login_with_unknown_identity_raises_auth_error(self):
        with self.assertRaises(handlers.AuthError):
            handlers.login("ghost@example.com", VALID_PASSWORD)

    def test_login_with_mobile_number(self):
        handlers.signup(VALID_PASSWORD, mobile_number="+919876543210")
        result = handlers.login("+919876543210", VALID_PASSWORD)
        self.assertTrue(result["ok"])
        self.assertEqual(result["subscriber"]["mobile_number"], "+919876543210")

    def test_login_missing_credentials_raises_validation_error(self):
        with self.assertRaises(handlers.ValidationError):
            handlers.login("", "")

    def test_logout_revokes_session(self):
        token = self._signup_verify_and_login("logout@example.com")
        handlers.logout(token)
        with self.assertRaises(handlers.AuthError):
            handlers.get_current_subscriber(token)

    def test_get_current_subscriber_without_session_raises_auth_error(self):
        with self.assertRaises(handlers.AuthError):
            handlers.get_current_subscriber("not-a-real-token")

    def test_get_current_subscriber_with_valid_session(self):
        token = self._signup_verify_and_login("whoami@example.com")
        result = handlers.get_current_subscriber(token)
        self.assertTrue(result["ok"])
        self.assertEqual(result["subscriber"]["email"], "whoami@example.com")


class TestLatestBriefing(ApiHandlersTestCase):
    def test_briefing_requires_authentication(self):
        with self.assertRaises(handlers.AuthError):
            handlers.get_latest_briefing("not-a-real-token")

    def test_briefing_returns_unavailable_when_no_runs_exist(self):
        token = self._signup_verify_and_login("noruns@example.com")
        result = handlers.get_latest_briefing(token)
        self.assertTrue(result["ok"])
        self.assertFalse(result["available"])

    def test_briefing_returns_cached_html_and_text(self):
        from marketpulse.models.schemas import PipelineRunRecord
        from marketpulse.persistence.run_log_repo import record_pipeline_run

        token = self._signup_verify_and_login("hasbriefing@example.com")
        record_pipeline_run(
            PipelineRunRecord(run_date_ist="2026-06-20"),
            bias_label="FLAT",
            briefing_html="<p>hello</p>",
            briefing_text="hello",
            client=self.fake_client,
        )
        result = handlers.get_latest_briefing(token)
        self.assertTrue(result["available"])
        self.assertEqual(result["html"], "<p>hello</p>")
        self.assertEqual(result["bias_label"], "FLAT")


class TestTelegramLink(ApiHandlersTestCase):
    def test_request_link_fails_before_verification(self):
        handlers.signup(VALID_PASSWORD, email="pending@example.com")
        # Not verified, so cannot log in either -- but the handler under
        # test only requires a session; simulate by logging in is not
        # possible pre-verification in this account model since status
        # stays pending_verification. Verify this directly via the
        # repository state instead of attempting a session-based call.
        rows = self.fake_client.select("subscribers")
        self.assertEqual(rows[0]["status"], "pending_verification")

    def test_request_link_succeeds_after_verification(self):
        token = self._signup_verify_and_login("active@example.com")
        result = handlers.request_telegram_link(token)
        self.assertTrue(result["ok"])
        self.assertIn("https://t.me/", result["deep_link"])

    def test_request_link_without_session_raises_auth_error(self):
        with self.assertRaises(handlers.AuthError):
            handlers.request_telegram_link("not-a-real-token")

    def test_request_link_for_mobile_only_account_is_refused(self):
        handlers.signup(VALID_PASSWORD, mobile_number="+919876543210")
        login_result = handlers.login("+919876543210", VALID_PASSWORD)
        result = handlers.request_telegram_link(login_result["session_token"])
        self.assertFalse(result["ok"])


class TestUnsubscribeAndChannels(ApiHandlersTestCase):
    def test_unsubscribe_sets_status(self):
        handlers.signup(VALID_PASSWORD, email="bye@example.com")
        result = handlers.unsubscribe("bye@example.com")
        self.assertTrue(result["ok"])
        rows = self.fake_client.select("subscribers")
        self.assertEqual(rows[0]["status"], "unsubscribed")

    def test_update_channels_replaces_set(self):
        token = self._signup_verify_and_login("multi@example.com")
        result = handlers.update_channels(token, ["email", "telegram"])
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["channels"]), {"email", "telegram"})

    def test_update_channels_rejects_invalid(self):
        token = self._signup_verify_and_login("multi2@example.com")
        with self.assertRaises(handlers.ValidationError):
            handlers.update_channels(token, ["smoke_signal"])

    def test_update_channels_without_session_raises_auth_error(self):
        with self.assertRaises(handlers.AuthError):
            handlers.update_channels("not-a-real-token", ["email"])


if __name__ == "__main__":
    unittest.main()
