"""
persistence/subscriber_repo.py

Repository for the `subscribers`, `email_verifications`, and
`telegram_links` tables. This is the persistence backbone for the
public signup web app (webapp/) and its API (api/), and for
email_system/sender.py's load_subscriber_list() (Email channel only).

Signup flow (Email channel, always required as the verified identity
regardless of which channels are ultimately enabled):

    1. api/signup creates a subscriber row (status='pending_verification')
       and an email_verifications row with a random token, then emails a
       confirmation link.
    2. Person clicks the link -> api/verify_email looks up the token,
       marks it used, and flips the subscriber to status='active'.

Telegram linking flow (optional, in addition to or instead of Email):

    1. An already-verified subscriber requests a Telegram link from the
       web app -> api/telegram_link_start creates a telegram_links row
       with a short-lived `link_code` and returns a deep-link URL
       (https://t.me/<bot_username>?start=<link_code>).
    2. The person taps it, Telegram opens a chat with the bot and sends
       `/start <link_code>` automatically -> the bot's webhook handler
       (delivery/telegram_sender.handle_start_command) looks up the code
       here, binds chat_id onto the subscriber, and marks it consumed.

WhatsApp linking is simpler in this MVP: WhatsApp Business numbers
(Twilio) require the person to message the sandbox/business number
first (a manual one-time step Twilio itself enforces), so there's no
separate "link" table needed -- the web app just collects the phone
number, and the WhatsApp sender treats a 24h-old unanswered number as
inactive (handled in delivery/whatsapp_sender.py, not here).
"""

from __future__ import annotations

import secrets
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

from marketpulse.models.schemas import DeliveryChannel, Subscriber
from marketpulse.persistence.supabase_client import SupabaseClient, get_client

SUBSCRIBERS_TABLE = "subscribers"
EMAIL_VERIFICATIONS_TABLE = "email_verifications"
TELEGRAM_LINKS_TABLE = "telegram_links"

# Backward-compat alias: earlier versions of this module exposed `TABLE`.
TABLE = SUBSCRIBERS_TABLE


# ---------------------------------------------------------------------------
# Core subscriber CRUD
# ---------------------------------------------------------------------------

def list_active_subscriber_emails(client: Optional[SupabaseClient] = None) -> list:
    """
    Returns the email addresses of every ACTIVE subscriber who has the
    Email channel enabled. This is what email_system/sender.py's
    load_subscriber_list() calls.
    """
    client = client or get_client()
    rows = client.select(
        SUBSCRIBERS_TABLE,
        params={"status": "eq.active", "select": "email,channels"},
    )
    return [row["email"] for row in rows if DeliveryChannel.EMAIL.value in (row.get("channels") or [])]


def list_active_subscribers_for_channel(
    channel: DeliveryChannel, client: Optional[SupabaseClient] = None
) -> list:
    """
    Returns full Subscriber objects (not just emails) for every ACTIVE
    subscriber with `channel` enabled and the necessary channel-specific
    identifier present. Used by the orchestrator's fan-out step
    (delivery/dispatcher.py) to know who to message on WhatsApp/Telegram.
    """
    client = client or get_client()
    rows = client.select(SUBSCRIBERS_TABLE, params={"status": "eq.active"})
    subscribers = [Subscriber.from_row(row) for row in rows]
    return [s for s in subscribers if s.is_deliverable_on(channel)]


def get_subscriber_by_email(email: str, client: Optional[SupabaseClient] = None) -> Optional[Subscriber]:
    client = client or get_client()
    rows = client.select(SUBSCRIBERS_TABLE, params={"email": f"eq.{email}"})
    return Subscriber.from_row(rows[0]) if rows else None


def get_subscriber_by_mobile(mobile_number: str, client: Optional[SupabaseClient] = None) -> Optional[Subscriber]:
    client = client or get_client()
    rows = client.select(SUBSCRIBERS_TABLE, params={"mobile_number": f"eq.{mobile_number}"})
    return Subscriber.from_row(rows[0]) if rows else None


def get_subscriber_by_login_id(login_id: str, client: Optional[SupabaseClient] = None) -> Optional[Subscriber]:
    """
    Looks up a subscriber by whichever identifier they used to sign in --
    email or mobile number, auto-detected by shape (contains '@' -> email).
    This is what api.handlers.login calls so the same sign-in form works
    regardless of which identifier the person typed.
    """
    client = client or get_client()
    if "@" in login_id:
        return get_subscriber_by_email(login_id, client=client)
    return get_subscriber_by_mobile(login_id, client=client)


def get_subscriber_by_id(subscriber_id: str, client: Optional[SupabaseClient] = None) -> Optional[Subscriber]:
    client = client or get_client()
    rows = client.select(SUBSCRIBERS_TABLE, params={"id": f"eq.{subscriber_id}"})
    return Subscriber.from_row(rows[0]) if rows else None


def create_pending_subscriber(
    password: str,
    email: Optional[str] = None,
    mobile_number: Optional[str] = None,
    channels: Optional[list] = None,
    whatsapp_number: Optional[str] = None,
    client: Optional[SupabaseClient] = None,
) -> dict:
    """
    Step 1 of signup: create (or fetch, if it already exists) a
    subscriber row in 'pending_verification' status with a hashed
    password. At least one of email/mobile_number must be supplied (the
    DB also enforces this via has_email_or_mobile) -- email remains the
    identity email verification anchors to; mobile_number alone is
    enough to sign in but does NOT skip email verification if an email
    was also given.

    Idempotent by email via on_conflict when email is present (matching
    the previous add_subscriber() behavior), but NO LONGER marks the row
    'active' immediately -- email verification (verify_subscriber_email
    below) is what activates it. This closes the gap where the old
    add_subscriber() let anyone activate delivery to an email address
    they didn't own.
    """
    if not email and not mobile_number:
        raise ValueError("At least one of email or mobile_number is required.")

    client = client or get_client()
    row = {
        "password_hash": generate_password_hash(password),
        "status": "pending_verification",
        "persona": "beginner",
        "channels": channels or [DeliveryChannel.EMAIL.value],
    }
    if email:
        row["email"] = email
    if mobile_number:
        row["mobile_number"] = mobile_number
    if whatsapp_number:
        row["whatsapp_number"] = whatsapp_number

    if email:
        return client.upsert(SUBSCRIBERS_TABLE, row, on_conflict="email")
    return client.upsert(SUBSCRIBERS_TABLE, row, on_conflict="mobile_number")


def verify_password(subscriber: Subscriber, password: str) -> bool:
    if not subscriber.password_hash:
        return False
    return check_password_hash(subscriber.password_hash, password)


def update_last_login(subscriber_id: str, login_at_iso: str, client: Optional[SupabaseClient] = None) -> None:
    client = client or get_client()
    client.update(
        SUBSCRIBERS_TABLE,
        params={"id": f"eq.{subscriber_id}"},
        patch={"last_login_at": login_at_iso},
    )


def add_subscriber(email: str, client: Optional[SupabaseClient] = None) -> dict:
    """
    Deprecated convenience wrapper kept for backward compatibility with
    earlier callers/tests: creates a pending subscriber AND immediately
    activates it, skipping email verification AND skipping password
    setup (a random unguessable password is generated since the column
    is required; this account simply can't be signed into until/unless
    a real password is set via a future "claim this account" flow).
    Prefer create_pending_subscriber() + verify_subscriber_email() for
    anything reachable from the public web app.
    """
    client = client or get_client()
    return client.upsert(
        SUBSCRIBERS_TABLE,
        {
            "email": email,
            "status": "active",
            "persona": "beginner",
            "channels": [DeliveryChannel.EMAIL.value],
            "password_hash": generate_password_hash(secrets.token_urlsafe(24)),
        },
        on_conflict="email",
    )


def unsubscribe(email: str, unsubscribed_at_iso: str, client: Optional[SupabaseClient] = None) -> None:
    client = client or get_client()
    client.update(
        SUBSCRIBERS_TABLE,
        params={"email": f"eq.{email}"},
        patch={"status": "unsubscribed", "unsubscribed_at": unsubscribed_at_iso},
    )


def pause_subscriber(email: str, client: Optional[SupabaseClient] = None) -> None:
    """Pause without fully unsubscribing -- e.g. a 'snooze for a week' feature."""
    client = client or get_client()
    client.update(SUBSCRIBERS_TABLE, params={"email": f"eq.{email}"}, patch={"status": "paused"})


def reactivate_subscriber(email: str, client: Optional[SupabaseClient] = None) -> None:
    client = client or get_client()
    client.update(
        SUBSCRIBERS_TABLE,
        params={"email": f"eq.{email}"},
        patch={"status": "active", "unsubscribed_at": None},
    )


def reactivate_subscriber_by_id(subscriber_id: str, client: Optional[SupabaseClient] = None) -> None:
    """Same as reactivate_subscriber(), keyed by id -- used for mobile-only
    signups (no email) that activate immediately, skipping verification."""
    client = client or get_client()
    client.update(
        SUBSCRIBERS_TABLE,
        params={"id": f"eq.{subscriber_id}"},
        patch={"status": "active", "unsubscribed_at": None},
    )


def set_channels(email: str, channels: list, client: Optional[SupabaseClient] = None) -> None:
    """
    Replace a subscriber's enabled-channel set entirely, e.g. when they
    toggle WhatsApp on/off from a "manage my subscription" page. Validity
    of channel names is enforced both here and by the DB CHECK constraint
    (schema.sql's channels_are_valid).
    """
    valid = {c.value for c in DeliveryChannel}
    invalid = set(channels) - valid
    if invalid:
        raise ValueError(f"Unknown delivery channel(s): {invalid}")
    client = client or get_client()
    client.update(SUBSCRIBERS_TABLE, params={"email": f"eq.{email}"}, patch={"channels": channels})


def set_channels_by_id(subscriber_id: str, channels: list, client: Optional[SupabaseClient] = None) -> None:
    """
    Same as set_channels(), but keyed by subscriber_id rather than email
    -- used by the authenticated dashboard (api.handlers, via the session
    token), since a mobile-only account has no email to key on.
    """
    valid = {c.value for c in DeliveryChannel}
    invalid = set(channels) - valid
    if invalid:
        raise ValueError(f"Unknown delivery channel(s): {invalid}")
    client = client or get_client()
    client.update(SUBSCRIBERS_TABLE, params={"id": f"eq.{subscriber_id}"}, patch={"channels": channels})


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

def create_email_verification(subscriber_id: str, client: Optional[SupabaseClient] = None) -> str:
    """Generates and stores a fresh verification token, returns it (the
    caller -- api/signup -- embeds it in the confirmation email link)."""
    client = client or get_client()
    token = secrets.token_urlsafe(32)
    client.insert(
        EMAIL_VERIFICATIONS_TABLE,
        {"token": token, "subscriber_id": subscriber_id},
        return_row=False,
    )
    return token


def verify_subscriber_email(
    token: str, verified_at_iso: str, client: Optional[SupabaseClient] = None
) -> Optional[Subscriber]:
    """
    Consumes a verification token: marks it used, and flips the linked
    subscriber to 'active'. Returns the now-active Subscriber, or None if
    the token doesn't exist or was already used (api/verify_email decides
    what HTTP response that maps to).
    """
    client = client or get_client()
    rows = client.select(EMAIL_VERIFICATIONS_TABLE, params={"token": f"eq.{token}"})
    if not rows or rows[0].get("used_at"):
        return None

    verification = rows[0]
    client.update(
        EMAIL_VERIFICATIONS_TABLE,
        params={"token": f"eq.{token}"},
        patch={"used_at": verified_at_iso},
    )
    client.update(
        SUBSCRIBERS_TABLE,
        params={"id": f"eq.{verification['subscriber_id']}"},
        patch={"status": "active", "verified_at": verified_at_iso},
    )
    sub_rows = client.select(SUBSCRIBERS_TABLE, params={"id": f"eq.{verification['subscriber_id']}"})
    return Subscriber.from_row(sub_rows[0]) if sub_rows else None


# ---------------------------------------------------------------------------
# Telegram linking
# ---------------------------------------------------------------------------

def create_telegram_link(subscriber_id: str, client: Optional[SupabaseClient] = None) -> str:
    """Generates a short-lived link_code for the Telegram /start deep-link flow."""
    client = client or get_client()
    link_code = secrets.token_urlsafe(16)
    client.insert(
        TELEGRAM_LINKS_TABLE,
        {"link_code": link_code, "subscriber_id": subscriber_id},
        return_row=False,
    )
    return link_code


def consume_telegram_link(
    link_code: str, chat_id: str, consumed_at_iso: str, client: Optional[SupabaseClient] = None
) -> Optional[Subscriber]:
    """
    Called by the Telegram bot webhook handler when a person sends
    `/start <link_code>`. Binds chat_id onto the subscriber, enables the
    Telegram channel if not already, and marks the link consumed.
    """
    client = client or get_client()
    rows = client.select(TELEGRAM_LINKS_TABLE, params={"link_code": f"eq.{link_code}"})
    if not rows or rows[0].get("consumed_at"):
        return None

    link = rows[0]
    client.update(
        TELEGRAM_LINKS_TABLE,
        params={"link_code": f"eq.{link_code}"},
        patch={"consumed_at": consumed_at_iso, "chat_id": chat_id},
    )

    sub_rows = client.select(SUBSCRIBERS_TABLE, params={"id": f"eq.{link['subscriber_id']}"})
    if not sub_rows:
        return None
    existing_channels = sub_rows[0].get("channels") or [DeliveryChannel.EMAIL.value]
    if DeliveryChannel.TELEGRAM.value not in existing_channels:
        existing_channels = existing_channels + [DeliveryChannel.TELEGRAM.value]

    client.update(
        SUBSCRIBERS_TABLE,
        params={"id": f"eq.{link['subscriber_id']}"},
        patch={"telegram_chat_id": chat_id, "channels": existing_channels},
    )
    updated = client.select(SUBSCRIBERS_TABLE, params={"id": f"eq.{link['subscriber_id']}"})
    return Subscriber.from_row(updated[0]) if updated else None
