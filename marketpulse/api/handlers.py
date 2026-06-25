"""
api/handlers.py

Framework-agnostic request handlers for the website: sign-up, sign-in,
session-aware "who am I", the authenticated briefing dashboard, and the
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
  - logout(session_token)                               POST /api/logout
  - get_current_subscriber(session_token)                GET /api/me
  - get_latest_briefing(session_token)                    GET /api/briefing/latest
  - request_telegram_link(session_token)                POST /api/telegram/link
  - unsubscribe(email)                                  POST /api/unsubscribe
  - update_channels(session_token, channels)            POST /api/channels

Account model: signing up always requires a password (this is what makes
"sign in and view the briefing on the website" possible at all) and at
least one of email / mobile_number. Email remains the verified anchor
identity when present -- request_telegram_link() and the dashboard
endpoints all operate on the already-authenticated session's
subscriber_id, never on a bare email/mobile string the caller could
forge, which is the core reason a session layer exists rather than just
trusting whatever identifier shows up in a request body.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

from marketpulse.models.schemas import DeliveryChannel

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
E164_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")

VALID_CHANNELS = {c.value for c in DeliveryChannel}

MIN_PASSWORD_LENGTH = 8


class ValidationError(Exception):
    """Raised for malformed input; api/app.py maps this to HTTP 400."""


class AuthError(Exception):
    """Raised for authentication failures; api/app.py maps this to HTTP 401."""


def _base_url() -> str:
    return os.environ.get("WEBAPP_BASE_URL", "https://marketpulseindia.app").rstrip("/")


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


def _validate_password(password: str) -> str:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


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
    )

    if not email and not mobile_number:
        raise ValidationError("Enter an email address or a mobile number to sign up.")

    clean_email = _validate_optional_email(email)
    clean_mobile = _validate_mobile_number(mobile_number)
    clean_password = _validate_password(password)
    clean_channels = _validate_channels(channels)
    clean_whatsapp = _validate_whatsapp_number(whatsapp_number, clean_channels)

    subscriber_row = create_pending_subscriber(
        clean_password,
        email=clean_email,
        mobile_number=clean_mobile,
        channels=clean_channels,
        whatsapp_number=clean_whatsapp,
    )

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
    Returns a session token on success -- the web app stores this and
    sends it back on every authenticated request (GET /api/me, GET
    /api/briefing/latest, etc).

    Deliberately returns the SAME generic failure message whether the
    account doesn't exist or the password is wrong, so a login attempt
    can't be used to enumerate which emails/numbers have accounts.
    """
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
