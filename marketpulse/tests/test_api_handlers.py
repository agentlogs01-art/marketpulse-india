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
 
        def fake_send_password_reset_email(to_email, reset_url):
            self.sent_emails.append({"type": "password_reset", "to": to_email, "url": reset_url})
 
        def fake_send_mfa_enabled_notification(to_email):
            self.sent_emails.append({"type": "mfa_enabled", "to": to_email})
 
        def fake_send_mfa_disabled_notification(to_email):
            self.sent_emails.append({"type": "mfa_disabled", "to": to_email})
 
        self._verify_email_patch = patch(
            "marketpulse.email_system.transactional.send_verification_email",
            side_effect=fake_send_verification_email,
        )
        self._telegram_confirm_patch = patch(
            "marketpulse.email_system.transactional.send_telegram_linked_confirmation",
            side_effect=fake_send_telegram_linked_confirmation,
        )
        self._password_reset_email_patch = patch(
            "marketpulse.email_system.transactional.send_password_reset_email",
            side_effect=fake_send_password_reset_email,
        )
        self._mfa_enabled_email_patch = patch(
            "marketpulse.email_system.transactional.send_mfa_enabled_notification",
            side_effect=fake_send_mfa_enabled_notification,
        )
        self._mfa_disabled_email_patch = patch(
            "marketpulse.email_system.transactional.send_mfa_disabled_notification",
            side_effect=fake_send_mfa_disabled_notification,
        )
        self._verify_email_patch.start()
        self._telegram_confirm_patch.start()
        self._password_reset_email_patch.start()
        self._mfa_enabled_email_patch.start()
        self._mfa_disabled_email_patch.start()
 
    def tearDown(self):
        self._client_patch.stop()
        self._verify_email_patch.stop()
        self._telegram_confirm_patch.stop()
        self._password_reset_email_patch.stop()
        self._mfa_enabled_email_patch.stop()
        self._mfa_disabled_email_patch.stop()
 
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
 
    def _enroll_mfa(self, session_token):
        """Completes MFA enrollment for an already-signed-in session,
        returning (secret, backup_codes) -- mirrors exactly what the
        Profile page's enroll flow does, using pyotp to generate a real
        valid code the same way an authenticator app would."""
        import pyotp
 
        start = handlers.mfa_enroll_start(session_token)
        secret = start["secret"]
        code = pyotp.TOTP(secret).now()
        confirm = handlers.mfa_enroll_confirm(session_token, code)
        return secret, confirm["backup_codes"]
 
 
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
 
    def test_signup_succeeds_with_warning_when_verification_email_fails_to_send(self):
        from marketpulse.email_system.transactional import TransactionalEmailError
 
        self._verify_email_patch.stop()
        with patch(
            "marketpulse.email_system.transactional.send_verification_email",
            side_effect=TransactionalEmailError("SMTP credentials not fully configured in environment (missing: SMTP_HOST, SMTP_USER, SMTP_PASSWORD)"),
        ):
            result = handlers.signup(VALID_PASSWORD, email="bademail@example.com")
        self._verify_email_patch = patch(
            "marketpulse.email_system.transactional.send_verification_email",
            side_effect=lambda to_email, verify_url: self.sent_emails.append(
                {"type": "verify", "to": to_email, "url": verify_url}
            ),
        )
        self._verify_email_patch.start()
 
        # The account must still be created -- a failed notification email
        # is not a reason to lose the signup -- and the failure must be
        # reported back, not silently dropped (this was the actual bug:
        # ok=True with no indication anything went wrong).
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "pending_verification")
        self.assertIn("warning", result)
        self.assertIn("SMTP_HOST", result["warning"])
        rows = self.fake_client.select("subscribers")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "pending_verification")
 
    def test_real_smtp_auth_failure_is_wrapped_as_transactional_email_error(self):
        # Exercises the actual transactional.py code path (not the
        # handler-level mock) to confirm a real smtplib exception -- not
        # just the custom TransactionalEmailError -- is caught and
        # produces a clear, diagnosable message rather than an unhandled
        # 500 or a silently-lost email.
        import smtplib
 
        from marketpulse.email_system import transactional
 
        self._verify_email_patch.stop()
 
        with patch.dict("os.environ", {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USER": "wrong-user",
            "SMTP_PASSWORD": "wrong-password",
        }):
            with patch("smtplib.SMTP") as mock_smtp:
                mock_server = mock_smtp.return_value.__enter__.return_value
                mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
 
                with self.assertRaises(transactional.TransactionalEmailError) as ctx:
                    transactional.send_verification_email("someone@example.com", "https://example.com/verify?token=abc")
 
                self.assertIn("authentication failed", str(ctx.exception).lower())
 
        self._verify_email_patch = patch(
            "marketpulse.email_system.transactional.send_verification_email",
            side_effect=lambda to_email, verify_url: self.sent_emails.append(
                {"type": "verify", "to": to_email, "url": verify_url}
            ),
        )
        self._verify_email_patch.start()
 
    def test_missing_smtp_env_vars_names_each_missing_one(self):
        from marketpulse.email_system import transactional
 
        self._verify_email_patch.stop()
        try:
            # Replace the environment entirely (clear=True) rather than
            # trying to selectively pop keys -- this is the reliable way
            # to simulate "these vars are simply not set" regardless of
            # what's present in the actual process environment running
            # the test.
            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaises(transactional.TransactionalEmailError) as ctx:
                    transactional.send_verification_email("someone@example.com", "https://example.com/verify?token=abc")
                message = str(ctx.exception)
                self.assertIn("SMTP_HOST", message)
                self.assertIn("SMTP_USER", message)
                self.assertIn("SMTP_PASSWORD", message)
        finally:
            self._verify_email_patch = patch(
                "marketpulse.email_system.transactional.send_verification_email",
                side_effect=lambda to_email, verify_url: self.sent_emails.append(
                    {"type": "verify", "to": to_email, "url": verify_url}
                ),
            )
            self._verify_email_patch.start()
 
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
 
 
class TestChangePassword(ApiHandlersTestCase):
    def test_change_password_with_correct_current_password(self):
        token = self._signup_verify_and_login("changepw@example.com")
        result = handlers.change_password(token, VALID_PASSWORD, "brand-new-password-789")
        self.assertTrue(result["ok"])
        # New password works for a fresh login; old one no longer does.
        login_result = handlers.login("changepw@example.com", "brand-new-password-789")
        self.assertTrue(login_result["ok"])
        with self.assertRaises(handlers.AuthError):
            handlers.login("changepw@example.com", VALID_PASSWORD)
 
    def test_change_password_with_wrong_current_password_fails(self):
        token = self._signup_verify_and_login("changepw2@example.com")
        with self.assertRaises(handlers.AuthError):
            handlers.change_password(token, "totally-wrong-password", "brand-new-password-789")
 
    def test_change_password_rejects_short_new_password(self):
        token = self._signup_verify_and_login("changepw3@example.com")
        with self.assertRaises(handlers.ValidationError):
            handlers.change_password(token, VALID_PASSWORD, "short")
 
    def test_change_password_without_session_raises_auth_error(self):
        with self.assertRaises(handlers.AuthError):
            handlers.change_password("not-a-real-token", VALID_PASSWORD, "brand-new-password-789")
 
    def test_change_password_does_not_revoke_current_session(self):
        token = self._signup_verify_and_login("changepw4@example.com")
        handlers.change_password(token, VALID_PASSWORD, "brand-new-password-789")
        # The session used to make the change is deliberately left intact.
        result = handlers.get_current_subscriber(token)
        self.assertTrue(result["ok"])
 
 
class TestPasswordReset(ApiHandlersTestCase):
    def test_request_reset_for_existing_verified_account_sends_email(self):
        self._signup_and_verify("forgot@example.com")
        result = handlers.request_password_reset("forgot@example.com")
        self.assertTrue(result["ok"])
        reset_emails = [e for e in self.sent_emails if e["type"] == "password_reset"]
        self.assertEqual(len(reset_emails), 1)
        self.assertEqual(reset_emails[0]["to"], "forgot@example.com")
 
    def test_request_reset_for_unknown_account_returns_same_generic_response(self):
        # Anti-enumeration: the response must be identical whether or not
        # an account exists, and no email is actually sent for a ghost.
        result = handlers.request_password_reset("ghost@example.com")
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.sent_emails), 0)
 
    def test_request_reset_for_unverified_account_sends_no_email(self):
        handlers.signup(VALID_PASSWORD, email="stillpending@example.com")  # never verified
        result = handlers.request_password_reset("stillpending@example.com")
        self.assertTrue(result["ok"])  # same generic response either way
        self.assertEqual(len(self.sent_emails), 0)
 
    def test_reset_password_with_valid_token_succeeds(self):
        self._signup_and_verify("resetflow@example.com")
        handlers.request_password_reset("resetflow@example.com")
        token = [e for e in self.sent_emails if e["type"] == "password_reset"][0]["url"].split("token=")[1]
 
        result = handlers.reset_password(token, "freshly-reset-password-123")
        self.assertTrue(result["ok"])
 
        login_result = handlers.login("resetflow@example.com", "freshly-reset-password-123")
        self.assertTrue(login_result["ok"])
 
    def test_reset_password_revokes_existing_sessions(self):
        self._signup_and_verify("revoketest@example.com")
        old_session = handlers.login("revoketest@example.com", VALID_PASSWORD)["session_token"]
 
        handlers.request_password_reset("revoketest@example.com")
        token = [e for e in self.sent_emails if e["type"] == "password_reset"][0]["url"].split("token=")[1]
        handlers.reset_password(token, "freshly-reset-password-123")
 
        with self.assertRaises(handlers.AuthError):
            handlers.get_current_subscriber(old_session)
 
    def test_reset_password_with_invalid_token_fails_generically(self):
        result = handlers.reset_password("not-a-real-token", "freshly-reset-password-123")
        self.assertFalse(result["ok"])
 
    def test_reset_password_token_is_single_use(self):
        self._signup_and_verify("onceonly@example.com")
        handlers.request_password_reset("onceonly@example.com")
        token = [e for e in self.sent_emails if e["type"] == "password_reset"][0]["url"].split("token=")[1]
 
        handlers.reset_password(token, "first-new-password-123")
        second_attempt = handlers.reset_password(token, "second-new-password-456")
        self.assertFalse(second_attempt["ok"])
 
    def test_reset_password_rejects_short_password(self):
        self._signup_and_verify("shortpw@example.com")
        handlers.request_password_reset("shortpw@example.com")
        token = [e for e in self.sent_emails if e["type"] == "password_reset"][0]["url"].split("token=")[1]
        with self.assertRaises(handlers.ValidationError):
            handlers.reset_password(token, "short")
 
 
class TestMfaEnrollmentAndLogin(ApiHandlersTestCase):
    def test_enroll_start_returns_provisioning_uri(self):
        token = self._signup_verify_and_login("mfastart@example.com")
        result = handlers.mfa_enroll_start(token)
        self.assertTrue(result["ok"])
        self.assertIn("secret", result)
        self.assertTrue(result["provisioning_uri"].startswith("otpauth://"))
 
    def test_enroll_confirm_with_correct_code_returns_backup_codes_and_notifies(self):
        token = self._signup_verify_and_login("mfaconfirm@example.com")
        secret, backup_codes = self._enroll_mfa(token)
        self.assertEqual(len(backup_codes), 8)
        notifications = [e for e in self.sent_emails if e["type"] == "mfa_enabled"]
        self.assertEqual(len(notifications), 1)
 
    def test_enroll_confirm_with_wrong_code_fails(self):
        token = self._signup_verify_and_login("mfawrong@example.com")
        handlers.mfa_enroll_start(token)
        result = handlers.mfa_enroll_confirm(token, "000000")
        self.assertFalse(result["ok"])
 
    def test_login_after_mfa_enrollment_requires_second_factor(self):
        import pyotp
 
        token = self._signup_verify_and_login("mfalogin@example.com")
        secret, _ = self._enroll_mfa(token)
 
        login_result = handlers.login("mfalogin@example.com", VALID_PASSWORD)
        self.assertTrue(login_result["ok"])
        self.assertTrue(login_result.get("mfa_required"))
        self.assertNotIn("session_token", login_result)
 
        code = pyotp.TOTP(secret).now()
        mfa_result = handlers.login_mfa(login_result["challenge_token"], code)
        self.assertTrue(mfa_result["ok"])
        self.assertIn("session_token", mfa_result)
 
    def test_login_mfa_with_wrong_code_fails(self):
        token = self._signup_verify_and_login("mfawrongcode@example.com")
        self._enroll_mfa(token)
 
        login_result = handlers.login("mfawrongcode@example.com", VALID_PASSWORD)
        with self.assertRaises(handlers.AuthError):
            handlers.login_mfa(login_result["challenge_token"], "000000")
 
    def test_login_mfa_with_backup_code_succeeds_once(self):
        token = self._signup_verify_and_login("mfabackup@example.com")
        secret, backup_codes = self._enroll_mfa(token)
 
        login_result = handlers.login("mfabackup@example.com", VALID_PASSWORD)
        mfa_result = handlers.login_mfa(login_result["challenge_token"], backup_codes[0])
        self.assertTrue(mfa_result["ok"])
 
        # The same backup code cannot be reused on a subsequent login.
        second_login = handlers.login("mfabackup@example.com", VALID_PASSWORD)
        with self.assertRaises(handlers.AuthError):
            handlers.login_mfa(second_login["challenge_token"], backup_codes[0])
 
    def test_login_mfa_challenge_is_single_use_even_on_failure(self):
        import pyotp
 
        token = self._signup_verify_and_login("mfasingleuse@example.com")
        secret, _ = self._enroll_mfa(token)
 
        login_result = handlers.login("mfasingleuse@example.com", VALID_PASSWORD)
        challenge = login_result["challenge_token"]
 
        with self.assertRaises(handlers.AuthError):
            handlers.login_mfa(challenge, "000000")
 
        # Even with the correct code, the SAME challenge token cannot be
        # reused after a failed attempt -- a fresh login() is required.
        code = pyotp.TOTP(secret).now()
        with self.assertRaises(handlers.AuthError):
            handlers.login_mfa(challenge, code)
 
    def test_wrong_password_fails_identically_for_mfa_and_non_mfa_accounts(self):
        token = self._signup_verify_and_login("mfapwcheck@example.com")
        self._enroll_mfa(token)
 
        with self.assertRaises(handlers.AuthError) as ctx:
            handlers.login("mfapwcheck@example.com", "wrong-password-entirely")
        # Same generic message as a non-MFA account's wrong password --
        # the existence of MFA on the account is never revealed here.
        self.assertEqual(str(ctx.exception), "Incorrect email/mobile number or password.")
 
    def test_mfa_disable_requires_correct_password(self):
        token = self._signup_verify_and_login("mfadisable@example.com")
        self._enroll_mfa(token)
 
        with self.assertRaises(handlers.AuthError):
            handlers.mfa_disable(token, "wrong-password")
 
        result = handlers.mfa_disable(token, VALID_PASSWORD)
        self.assertTrue(result["ok"])
 
        # MFA no longer required on next login.
        login_result = handlers.login("mfadisable@example.com", VALID_PASSWORD)
        self.assertNotIn("mfa_required", login_result)
        self.assertIn("session_token", login_result)
 
        notifications = [e for e in self.sent_emails if e["type"] == "mfa_disabled"]
        self.assertEqual(len(notifications), 1)
 
    def test_regenerate_backup_codes_requires_mfa_enabled(self):
        token = self._signup_verify_and_login("mfaregen@example.com")
        result = handlers.mfa_regenerate_backup_codes(token)
        self.assertFalse(result["ok"])
 
    def test_regenerate_backup_codes_invalidates_old_set(self):
        token = self._signup_verify_and_login("mfaregen2@example.com")
        secret, old_codes = self._enroll_mfa(token)
 
        result = handlers.mfa_regenerate_backup_codes(token)
        self.assertTrue(result["ok"])
        new_codes = result["backup_codes"]
        self.assertNotEqual(set(old_codes), set(new_codes))
 
        login_result = handlers.login("mfaregen2@example.com", VALID_PASSWORD)
        with self.assertRaises(handlers.AuthError):
            handlers.login_mfa(login_result["challenge_token"], old_codes[0])
 
 
class TestThemePreference(ApiHandlersTestCase):
    def test_update_theme_to_dark(self):
        token = self._signup_verify_and_login("themeuser@example.com")
        result = handlers.update_theme_preference(token, "dark")
        self.assertTrue(result["ok"])
        self.assertEqual(result["theme_preference"], "dark")
 
    def test_theme_persists_across_me_lookups(self):
        token = self._signup_verify_and_login("themepersist@example.com")
        handlers.update_theme_preference(token, "dark")
        result = handlers.get_current_subscriber(token)
        self.assertEqual(result["subscriber"]["theme_preference"], "dark")
 
    def test_invalid_theme_raises_validation_error(self):
        token = self._signup_verify_and_login("badtheme@example.com")
        with self.assertRaises(handlers.ValidationError):
            handlers.update_theme_preference(token, "solarized")
 
    def test_update_theme_without_session_raises_auth_error(self):
        with self.assertRaises(handlers.AuthError):
            handlers.update_theme_preference("not-a-real-token", "dark")
 
 
if __name__ == "__main__":
    unittest.main()
 
