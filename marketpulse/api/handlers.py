"""
api/handlers.py
 
Framework-agnostic request handlers for the website: sign-up, sign-in
(with optional MFA challenge), session-aware "who am I", the
authenticated briefing dashboard, account/profile management (password
change, password reset, MFA enrollment, theme preference), and the
existing verification/telegram-link/unsubscribe flows. Each function
takes plain Python args (already parsed from whatever HTTP framework is
in front of it -- see api/app.py for the Flask wiring) and returns a
plain dict, so these are trivially testable without spinning up a real
HTTP server.
 
Endpoints implemented here:
  - signup(password, email, mobile_number, channels, whatsapp_number)
                                                        POST /api/signup
  - verify_email(token)                                 POST /api/verify
  - login(login_id, password)                           POST /api/login
  - login_mfa(challenge_token, code)                    POST /api/login/mfa
  - logout(session_token)                               POST /api/logout
  - get_current_subscriber(session_token)                GET /api/me
  - get_latest_briefing(session_token)                    GET /api/briefing/latest
  - request_telegram_link(session_token)                POST /api/telegram/link
  - unsubscribe(email)                                  POST /api/unsubscribe
  - update_channels(session_token, channels)            POST /api/channels
  - change_password(session_token, current_password, new_password)
                                                        POST /api/password/change
  - request_password_reset(login_id)                    POST /api/password/forgot
  - reset_password(token, new_password)                 POST /api/password/reset
  - mfa_enroll_start(session_token)                     POST /api/mfa/enroll/start
  - mfa_enroll_confirm(session_token, code)             POST /api/mfa/enroll/confirm
  - mfa_disable(session_token, password)                POST /api/mfa/disable
  - mfa_regenerate_backup_codes(session_token)          POST /api/mfa/backup-codes/regenerate
  - update_theme_preference(session_token, theme)       POST /api/theme
 
Account model: signing up always requires a password (this is what makes
"sign in and view the briefing on the website" possible at all) and at
least one of email / mobile_number. Email remains the verified anchor
identity when present -- request_telegram_link() and the dashboard
endpoints all operate on the already-authenticated session's
subscriber_id, never on a bare email/mobile string the caller could
forge, which is the core reason a session layer exists rather than just
trusting whatever identifier shows up in a request body.
 
MFA model: when enabled, a correct password alone is never sufficient to
obtain a session -- login() returns a short-lived challenge token instead
of a session token, and login_mfa() is what actually issues the session,
only after a correct TOTP/backup code is presented against that
challenge. See persistence/mfa_repo.py's module docstring for the full
enrollment and verification design.
"""
from __future__ import annotations

import os
import re
import string
from datetime import datetime, timezone
from typing import Optional
from zxcvbn import zxcvbn

from marketpulse.models.schemas import DeliveryChannel
from marketpulse.persistence.supabase_client import SupabaseRequestError


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
E164_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")
TOTP_CODE_RE = re.compile(r"^\d{6}$")

VALID_CHANNELS = {c.value for c in DeliveryChannel}

MIN_PASSWORD_LENGTH = 12

VALID_THEMES = {"light", "dark"}


class ValidationError(Exception):
    """Raised for malformed input; api/app.py maps this to HTTP 400."""


class AuthError(Exception):
    """Raised for authentication failures; api/app.py maps this to HTTP 401."""


def _base_url() -> str:
    """
    Dynamically computes the web application root URL.
    Prioritizes Railway's dynamically assigned deployment URL,
    then falls back to your local environment configuration or production domain.
    """
    # 1. Look for custom variable, fallback to Railway's public URL, then standard domain
    url = (
        os.environ.get("WEBAPP_BASE_URL") or 
        os.environ.get("RAILWAY_PUBLIC_DOMAIN") or 
        "https://marketpulseindia.app"
    )
    
    # 2. Clean up leading/trailing whitespaces and remove trailing slashes completely
    return url.strip().rstrip("/")


def _validate_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not email or not EMAIL_RE.match(email):
        raise ValidationError("Please enter a valid email address.")
    return email


def _validate_optional_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    return _validate_email(email)


def _validate_mobile_number(number: Optional[str]) -> Optional[str]:
    if not number:
        return None
    number = number.strip()
    if not E164_PHONE_RE.match(number):
        raise ValidationError(
            "Mobile number must be in international format, e.g. +919876543210."
        )
    return number


def _validate_password(password: str, user_context: list = None) -> str:
    """
    Validates password using modern NIST/OWASP predictability standards.
    user_context: Pass [username, email, first_name] to catch context-specific guessing.
    """

    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    # Run pattern, sequence, and common dictionary analysis
    # user_inputs array tells zxcvbn to also flag passwords containing user data
    analysis = zxcvbn(password, user_inputs=user_context)
    
    # zxcvbn scores range from 0 (very guessable) to 4 (very secure). 
    # A score of less than 3 is generally considered too predictable for production.
    if analysis['score'] < 3:
        # Optional: zxcvbn provides helpful feedback strings on why it failed
        feedback = analysis['feedback'].get('warning', 'Password is too predictable.')
        raise ValidationError(f"Weak Password: {feedback}")

    return password

def _validate_mfa_code(code: str) -> str:
    code = (code or "").strip().replace(" ", "")
    if not code:
        raise ValidationError("Enter the 6-digit code from your authenticator app, or a backup code.")
    return code

def _validate_channels(channels: Optional[list]) -> list:
    channels = channels or [DeliveryChannel.EMAIL.value]
    invalid = set(channels) - VALID_CHANNELS
    if invalid:
        raise ValidationError(f"Unknown delivery channel(s): {sorted(invalid)}")
    if not channels:
        raise ValidationError("Select at least one delivery channel.")
    return channels

def _validate_whatsapp_number(number: Optional[str], channels: list) -> Optional[str]:
    if DeliveryChannel.WHATSAPP.value not in channels:
        return None
    if not number or not E164_PHONE_RE.match(number):
        raise ValidationError(
            "WhatsApp requires a valid phone number in international format, e.g. +919876543210."
        )
    return number


def _require_session(session_token: Optional[str]):
    """
    Resolves a session token to a Subscriber, or raises AuthError. Every
    authenticated handler calls this first -- it's the single choke point
    that makes "you must be signed in to see this" actually true.
    """
    from marketpulse.persistence.session_repo import get_subscriber_id_for_token
    from marketpulse.persistence.subscriber_repo import get_subscriber_by_id

    subscriber_id = get_subscriber_id_for_token(session_token or "")
    if not subscriber_id:
        raise AuthError("Please sign in to continue.")

    subscriber = get_subscriber_by_id(subscriber_id)
    if subscriber is None:
        raise AuthError("Please sign in to continue.")
    return subscriber


# ---------------------------------------------------------------------------
# Signup / email verification
# ---------------------------------------------------------------------------

def signup(
    password: str,
    email: Optional[str] = None,
    mobile_number: Optional[str] = None,
    channels: Optional[list] = None,
    whatsapp_number: Optional[str] = None,
) -> dict:
    """
    Public signup endpoint. Requires a password and at least one of
    email/mobile_number. If an email is given, a verification link is
    sent and the account stays 'pending_verification' until clicked --
    the same gate as before, now also gating sign-in (an unverified
    account can still authenticate, but request_telegram_link and channel
    delivery remain blocked until verified; see login()'s docstring).

    A mobile-only signup (no email) skips the email-verification step
    entirely, since there's no email to verify -- it activates
    immediately. This mirrors how most consumer apps treat
    phone-number-only accounts, but means mobile-only accounts cannot
    use Telegram linking, which intentionally requires a verified email
    anchor (see request_telegram_link).
    """
    from marketpulse.email_system.transactional import TransactionalEmailError, send_verification_email
    from marketpulse.persistence.subscriber_repo import (
        create_email_verification,
        create_pending_subscriber,
        get_client,
    )

    if not email and not mobile_number:
        raise ValidationError("Enter an email address or a mobile number to sign up.")

    clean_email = _validate_optional_email(email)
    clean_mobile = _validate_mobile_number(mobile_number)
    clean_password = _validate_password(password)
    clean_channels = _validate_channels(channels)
    clean_whatsapp = _validate_whatsapp_number(whatsapp_number, clean_channels)

    # --- MANUAL DE-DUPLICATION CHECK ---
    if clean_whatsapp:
        client = get_client()
        # Check if any subscriber row already uses this whatsapp number
        existing = client.select("subscribers", params={"whatsapp_number": f"eq.{clean_whatsapp}"})
        if existing:
            error_msg = "This WhatsApp number is already linked to another account."
            return {
                "ok": False,
                "error": error_msg,
				"reason": error_msg,
                "data": {"ok": False,"error": error_msg, "reason": error_msg}
            }, 400

    # --- TRY/EXCEPT BLOCK TO CATCH DB UNIQUE CONSTRAINT VALUE_ERRORS ---
    try:
        subscriber_row = create_pending_subscriber(
            clean_password,
            email=clean_email,
            mobile_number=clean_mobile,
            channels=clean_channels,
            whatsapp_number=clean_whatsapp,
        )
    except Exception as exc:
        # Convert the entire error object to a lowercase string to catch it anywhere
        exc_text = str(exc).lower()
        
        # Pull internal attributes if they exist on the exception object
        for attr in ["text", "message", "details", "hint", "code"]:
            if hasattr(exc, attr):
                exc_text += " " + str(getattr(exc, attr, "")).lower()

        # Target the WhatsApp unique key violation or any mentions of the field name
        if "whatsapp_number_key" in exc_text or "whatsapp" in exc_text:
            error_msg = "This WhatsApp number is already linked to another account."
        elif "mobile_number_key" in exc_text or "mobile" in exc_text:
            error_msg = "This mobile number is already linked to another account."
        else:
            # Fallback to prevent silent failures so you can print the real error structure
            error_msg = f"A database conflict occurred during signup. Raw details: {str(exc)}"

        return {
            "ok": False,
            "error": error_msg,
            "data": {
                "error": error_msg,
                "reason": error_msg
            }
        }, 200

    if not clean_email:
        # No email to verify -- activate immediately (mobile-only account).
        from marketpulse.persistence.subscriber_repo import reactivate_subscriber_by_id

        reactivate_subscriber_by_id(subscriber_row["id"])
        return {"ok": True, "status": "active"}

    token = create_email_verification(subscriber_row["id"])
    verify_url = f"{_base_url()}/verify?token={token}"

    try:
        send_verification_email(clean_email, verify_url)
    except TransactionalEmailError as exc:
        # Signup itself succeeded (the row exists); only the notification
        # email failed to send. Surface this distinctly so the web app can
        # show "almost there, but we couldn't email you" rather than a
        # generic failure that implies nothing was saved.
        return {
            "ok": True,
            "status": "pending_verification",
            "warning": f"Account created but verification email failed to send: {exc}",
        }

    return {"ok": True, "status": "pending_verification"}
	


def verify_email(token: str) -> dict:
    """
    Confirms a signup. Called when the person clicks the link from
    signup()'s verification email. Idempotent in effect: re-visiting an
    already-used link returns ok=False with a clear reason rather than
    re-activating or erroring.
    """
    from marketpulse.persistence.subscriber_repo import verify_subscriber_email

    if not token or not isinstance(token, str):
        raise ValidationError("Missing verification token.")

    subscriber = verify_subscriber_email(token, datetime.now(timezone.utc).isoformat())
    if subscriber is None:
        return {"ok": False, "reason": "This verification link is invalid or has already been used."}

    return {"ok": True, "status": "active", "email": subscriber.email, "channels": subscriber.channels}


# ---------------------------------------------------------------------------
# Sign-in / sign-out
# ---------------------------------------------------------------------------

def login(login_id: str, password: str) -> dict:
    """
    Signs in with either an email or a mobile number plus password.
 
    If the account does NOT have MFA enabled: returns a session token
    directly, as before -- the web app stores this and sends it back on
    every authenticated request (GET /api/me, GET /api/briefing/latest,
    etc).
 
    If the account DOES have MFA enabled: a correct password is
    necessary but not sufficient. This returns `{"ok": True,
    "mfa_required": True, "challenge_token": ...}` instead of a session
    token. The web app then prompts for a 6-digit authenticator code (or
    a backup code) and calls login_mfa() with that challenge_token to
    actually obtain a session -- see login_mfa()'s docstring.
 
    Deliberately returns the SAME generic failure message whether the
    account doesn't exist or the password is wrong, so a login attempt
    can't be used to enumerate which emails/numbers have accounts. This
    holds even for MFA-enabled accounts: a wrong password fails exactly
    the same way whether or not MFA is configured, so the existence of
    MFA on an account is never revealed to someone who doesn't already
    know the correct password.
    """
    from marketpulse.persistence.mfa_repo import create_mfa_challenge
    from marketpulse.persistence.session_repo import create_session
    from marketpulse.persistence.subscriber_repo import (
        get_subscriber_by_login_id,
        update_last_login,
        verify_password,
    )

    login_id = (login_id or "").strip()
    if not login_id or not password:
        raise ValidationError("Enter your email or mobile number and password.")

    subscriber = get_subscriber_by_login_id(login_id)
    if subscriber is None or not verify_password(subscriber, password):
        raise AuthError("Incorrect email/mobile number or password.")

    if subscriber.status == "unsubscribed" or (
        hasattr(subscriber.status, "value") and subscriber.status.value == "unsubscribed"
    ):
        raise AuthError("This account has been unsubscribed. Sign up again to reactivate.")

    if subscriber.mfa_enabled:    
      challenge_token = create_mfa_challenge(subscriber.id)
      return {"ok": True, "mfa_required": True, "challenge_token": challenge_token}
    now_iso = datetime.now(timezone.utc).isoformat()
    update_last_login(subscriber.id, now_iso)
    token = create_session(subscriber.id)

    return {"ok": True, "session_token": token, "subscriber": subscriber.to_public_dict()}

def login_mfa(challenge_token: str, code: str) -> dict:
    """
    Second step of sign-in for an MFA-enabled account: consumes the
    challenge_token returned by login() and verifies the supplied
    6-digit TOTP code (or a backup code) against the account that
    challenge was issued for. Only on success is a real session issued.
 
    The challenge token itself already proves a correct password
    preceded this call (see mfa_repo.consume_mfa_challenge's docstring);
    this function's job is solely to check the second factor.
 
    A wrong code does not consume the challenge token -- the person gets
    multiple attempts within the challenge's 5-minute window, since
    fat-fingering a TOTP code is common and shouldn't force a full
    password re-entry. The challenge token IS single-use in the sense
    that it cannot be reused after this function returns successfully
    (it's consumed atomically up front), but a failed code check leaves
    it... actually consumed too, by current implementation, since
    consume_mfa_challenge() is called before code verification. This is
    intentional: re-validating against an already-spent challenge would
    mean the underlying token simply IS the proof of "password was
    correct," and replaying it indefinitely while guessing codes would
    turn that proof into a 6-digit-only brute-force surface with no
    password rate-limit backing it. Treating the challenge as consumed
    on first use (regardless of code correctness) ensures a fresh
    login() call -- and a fresh password check -- is required after any
    failed attempt.
    """
    from marketpulse.persistence.mfa_repo import consume_mfa_challenge, verify_mfa_code
    from marketpulse.persistence.session_repo import create_session
    from marketpulse.persistence.subscriber_repo import get_subscriber_by_id, update_last_login
 
    if not challenge_token:
        raise ValidationError("Missing or expired sign-in challenge. Please sign in again.")
    clean_code = _validate_mfa_code(code)
 
    subscriber_id = consume_mfa_challenge(challenge_token)
    if subscriber_id is None:
        raise AuthError("This sign-in attempt has expired. Please sign in again.")
 
    subscriber = get_subscriber_by_id(subscriber_id)
    if subscriber is None:
        raise AuthError("This sign-in attempt has expired. Please sign in again.")
 
    if not verify_mfa_code(subscriber, clean_code):
        raise AuthError("Incorrect code. Please sign in again and try once more.")
 
    now_iso = datetime.now(timezone.utc).isoformat()
    update_last_login(subscriber.id, now_iso)
    token = create_session(subscriber.id)
 
    return {"ok": True, "session_token": token, "subscriber": subscriber.to_public_dict()}

def logout(session_token: str) -> dict:
    from marketpulse.persistence.session_repo import revoke_session

    if session_token:
        revoke_session(session_token)
    return {"ok": True}


def get_current_subscriber(session_token: str) -> dict:
    """Backs GET /api/me -- lets the web app restore a signed-in session
    on page reload without re-prompting for credentials."""
    subscriber = _require_session(session_token)
    return {"ok": True, "subscriber": subscriber.to_public_dict()}


# ---------------------------------------------------------------------------
# Authenticated dashboard: view the briefing on the website
# ---------------------------------------------------------------------------

def get_latest_briefing(session_token: str) -> dict:
    """
    Returns the most recently assembled daily briefing for display inside
    the signed-in dashboard -- this is the "view MarketPulse on the
    website after login" feature. Reads the cached render
    (pipeline_runs.briefing_html / briefing_text) rather than re-running
    the pipeline per page view.

    Authentication only gates ACCESS to this endpoint; the briefing
    content itself is identical for every subscriber (single beginner
    persona, MVP scope) -- there's no per-subscriber personalization to
    apply here yet.
    """
    _require_session(session_token)  # raises AuthError if not signed in

    from marketpulse.persistence.run_log_repo import get_latest_run

    run = get_latest_run()
    if run is None:
        return {"ok": True, "available": False, "reason": "No briefing has been published yet."}

    return {
        "ok": True,
        "available": True,
        "run_date": run.get("run_date_ist"),
        "bias_label": run.get("bias_label"),
        "html": run.get("briefing_html"),
        "text": run.get("briefing_text"),
        "suppressed": run.get("suppressed", False),
    }


# ---------------------------------------------------------------------------
# Telegram linking / unsubscribe / channel management
# ---------------------------------------------------------------------------

def request_telegram_link(session_token: str) -> dict:
    """
    Generates a Telegram deep-link for the signed-in subscriber. Requires
    an ACTIVE account with a verified email anchor -- Telegram's chat_id
    binding stays anchored to a verified identity rather than an
    arbitrary unverified claim, and a mobile-only account (no email
    verification step exists for it) is therefore not eligible until it
    also adds and verifies an email.
    """
    from marketpulse.delivery.telegram_sender import build_deep_link
    from marketpulse.models.schemas import SubscriberStatus
    from marketpulse.persistence.subscriber_repo import create_telegram_link

    subscriber = _require_session(session_token)
    if subscriber.status != SubscriberStatus.ACTIVE:
        return {"ok": False, "reason": "Please verify your email before linking Telegram."}
    if not subscriber.email or not subscriber.verified_at:
        return {"ok": False, "reason": "Add and verify an email address before linking Telegram."}

    link_code = create_telegram_link(subscriber.id)
    return {"ok": True, "deep_link": build_deep_link(link_code)}


def unsubscribe(email: str) -> dict:
    from marketpulse.persistence.subscriber_repo import unsubscribe as unsubscribe_repo

    clean_email = _validate_email(email)
    unsubscribe_repo(clean_email, datetime.now(timezone.utc).isoformat())
    return {"ok": True, "status": "unsubscribed"}


def update_channels(session_token: str, channels: list) -> dict:
    from marketpulse.persistence.subscriber_repo import set_channels_by_id

    subscriber = _require_session(session_token)
    clean_channels = _validate_channels(channels)
    set_channels_by_id(subscriber.id, clean_channels)
    return {"ok": True, "channels": clean_channels}

# ---------------------------------------------------------------------------
# Password change (authenticated) & password reset (unauthenticated)
# ---------------------------------------------------------------------------
 
def change_password(session_token: str, current_password: str, new_password: str) -> dict:
    """
    Profile-page password change for an already-signed-in subscriber.
    Requires the CURRENT password to be supplied and correct -- a valid
    session alone is not sufficient to change the password, so a hijacked
    but still-active session (e.g. someone using a forgotten-to-sign-out
    shared computer) can't silently lock the real owner out by changing
    the password without ever knowing it. Sessions are not revoked on a
    successful change (current session keeps working); MFA-style "sign
    out everywhere" is a separate, more drastic action this endpoint
    intentionally does not perform.
    """
    from marketpulse.persistence.subscriber_repo import update_password, verify_password
 
    subscriber = _require_session(session_token)
    if not current_password or not verify_password(subscriber, current_password):
        raise AuthError("Current password is incorrect.")
    clean_new_password = _validate_password(new_password)
    update_password(subscriber.id, clean_new_password)
    return {"ok": True}
 
 
def request_password_reset(login_id: str) -> dict:
    """
    "Forgot password" entry point. Looks up the account by email or
    mobile number and, if found AND it has a verified email on file,
    emails a one-time reset link. Returns the SAME generic success
    response whether or not an account exists for the given identifier --
    this is the same anti-enumeration posture as login(): a "forgot
    password" form cannot be used to test which emails/numbers have
    registered accounts. The actual email-or-not decision happens
    silently inside this function.
 
    Mobile-only accounts (no email on file) cannot use this flow, since
    there's no email to send a reset link to -- the generic response
    covers this case too, so it isn't distinguishable from "no such
    account" by the caller.
    """
    import logging
 
    from marketpulse.email_system.transactional import TransactionalEmailError, send_password_reset_email
    from marketpulse.persistence.subscriber_repo import create_password_reset, get_subscriber_by_login_id
 
    logger = logging.getLogger("marketpulse.password_reset")
 
    clean_login_id = (login_id or "").strip()
    if not clean_login_id:
        raise ValidationError("Enter your email or mobile number.")
 
    generic_response = {
        "ok": True,
        "message": "If an account exists for that email or mobile number, a password reset link has been sent.",
    }
 
    subscriber = get_subscriber_by_login_id(clean_login_id)
    if subscriber is None or not subscriber.email or not subscriber.verified_at:
        return generic_response
 
    token = create_password_reset(subscriber.id)
    reset_url = f"{_base_url()}/reset-password?token={token}"
 
    try:
        send_password_reset_email(subscriber.email, reset_url)
    except TransactionalEmailError as exc:
        # Same reasoning as signup()'s email-failure handling: don't let
        # an SMTP outage be invisible. The person still sees the generic
        # success message (so this can't be used to confirm an account
        # exists by comparing error vs. success responses), but the
        # failure is logged loudly server-side for diagnosis.
        logger.error(
            "Password reset email failed to send to %s: %s: %s",
            subscriber.email, type(exc).__name__, exc,
        )
 
    return generic_response
 
 
def reset_password(token: str, new_password: str) -> dict:
    """
    Consumes a password-reset token and sets a new password. Returns a
    generic failure reason regardless of whether the token was invalid,
    already used, or expired -- mirroring login()'s anti-enumeration
    posture, since distinguishing these cases would let an attacker probe
    which tokens were ever issued.
    """
    from marketpulse.persistence.session_repo import revoke_all_sessions_for_subscriber
    from marketpulse.persistence.subscriber_repo import consume_password_reset
 
    if not token:
        raise ValidationError("Missing password reset token.")
    clean_new_password = _validate_password(new_password)
 
    subscriber = consume_password_reset(token, clean_new_password, datetime.now(timezone.utc).isoformat())
    if subscriber is None:
        return {"ok": False, "reason": "This password reset link is invalid or has expired."}
 
    # Unlike change_password() (which deliberately leaves the current
    # session alone), a password reset DOES revoke every existing
    # session for the account -- if the reset was triggered because the
    # password leaked or was forgotten under suspicious circumstances,
    # any session an attacker may have established earlier should not
    # silently continue to work after the legitimate owner takes back
    # control via reset.
    revoke_all_sessions_for_subscriber(subscriber.id)
 
    return {"ok": True}
 
 
# ---------------------------------------------------------------------------
# Multi-factor authentication (TOTP) -- Profile page management
# ---------------------------------------------------------------------------
 
def mfa_enroll_start(session_token: str) -> dict:
    """
    Begins (or restarts) MFA enrollment for the signed-in subscriber.
    Returns a provisioning URI for the web app to render as a QR code,
    plus the raw secret for manual entry as a fallback. MFA is NOT yet
    enabled at this point -- see mfa_enroll_confirm().
    """
    from marketpulse.persistence.mfa_repo import generate_enrollment_secret
 
    subscriber = _require_session(session_token)
    account_label = subscriber.email or subscriber.mobile_number or "MarketPulse India"
    result = generate_enrollment_secret(subscriber.id, account_label)
    return {"ok": True, "secret": result["secret"], "provisioning_uri": result["provisioning_uri"]}
 
 
def mfa_enroll_confirm(session_token: str, code: str) -> dict:
    """
    Completes MFA enrollment: verifies the first code produced by the
    person's newly-scanned authenticator app. On success, MFA is enabled
    and a set of plaintext backup codes is returned -- the ONLY time
    they are ever available in plaintext; the web app must show these to
    the person immediately and tell them to store them safely, since
    there is no "view my backup codes again" endpoint by design (only
    their hashes are kept).
    """
    import logging
 
    from marketpulse.email_system.transactional import TransactionalEmailError, send_mfa_enabled_notification
    from marketpulse.persistence.mfa_repo import confirm_enrollment
 
    logger = logging.getLogger("marketpulse.mfa")
 
    subscriber = _require_session(session_token)
    clean_code = _validate_mfa_code(code)
 
    backup_codes = confirm_enrollment(subscriber.id, clean_code)
    if backup_codes is None:
        return {"ok": False, "reason": "Incorrect code. Please check your authenticator app and try again."}
 
    if subscriber.email:
        try:
            send_mfa_enabled_notification(subscriber.email)
        except TransactionalEmailError as exc:
            # The security-relevant action (enabling MFA) already
            # succeeded; a failed notification email shouldn't undo it
            # or fail the request -- just log it, same pattern as every
            # other transactional-email send in this file.
            logger.error("MFA-enabled notification failed to send to %s: %s", subscriber.email, exc)
 
    return {"ok": True, "backup_codes": backup_codes}
 
 
def mfa_disable(session_token: str, password: str) -> dict:
    """
    Turns MFA off. Requires the current password as a step-up
    confirmation -- a valid session alone should not be sufficient to
    remove a security control from the account, for the same reasoning
    as change_password() requiring the current password.
    """
    import logging
 
    from marketpulse.email_system.transactional import TransactionalEmailError, send_mfa_disabled_notification
    from marketpulse.persistence.mfa_repo import disable_mfa
    from marketpulse.persistence.subscriber_repo import verify_password
 
    logger = logging.getLogger("marketpulse.mfa")
 
    subscriber = _require_session(session_token)
    if not password or not verify_password(subscriber, password):
        raise AuthError("Current password is incorrect.")
 
    disable_mfa(subscriber.id)
 
    if subscriber.email:
        try:
            send_mfa_disabled_notification(subscriber.email)
        except TransactionalEmailError as exc:
            logger.error("MFA-disabled notification failed to send to %s: %s", subscriber.email, exc)
 
    return {"ok": True}
 
 
def mfa_regenerate_backup_codes(session_token: str) -> dict:
    """
    Invalidates all existing backup codes and issues a fresh set, e.g.
    after the person suspects one may have leaked. Requires MFA to
    already be enabled.
    """
    from marketpulse.persistence.mfa_repo import regenerate_backup_codes
 
    subscriber = _require_session(session_token)
    codes = regenerate_backup_codes(subscriber.id)
    if codes is None:
        return {"ok": False, "reason": "Multi-factor authentication is not enabled on this account."}
    return {"ok": True, "backup_codes": codes}
 
 
# ---------------------------------------------------------------------------
# Theme preference
# ---------------------------------------------------------------------------
 
def update_theme_preference(session_token: str, theme: str) -> dict:
    """
    Persists the subscriber's chosen UI theme so it follows them across
    devices/sessions. The web app also keeps an immediate client-side
    copy (so the toggle feels instant and works even while this request
    is in flight) but this is the durable source of truth on next sign-in
    from a different browser/device.
    """
    from marketpulse.persistence.subscriber_repo import set_theme_preference
 
    subscriber = _require_session(session_token)
    clean_theme = (theme or "").strip().lower()
    if clean_theme not in VALID_THEMES:
        raise ValidationError(f"Theme must be one of: {sorted(VALID_THEMES)}")
 
    set_theme_preference(subscriber.id, clean_theme)
    return {"ok": True, "theme_preference": clean_theme}
 
