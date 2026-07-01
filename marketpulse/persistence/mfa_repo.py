"""
persistence/mfa_repo.py

Repository + crypto logic for TOTP-based multi-factor authentication
(RFC 6238 -- compatible with Google Authenticator, Authy, 1Password,
etc.) and the MFA login-challenge flow.

Enrollment flow (authenticated subscriber, from the Profile page):

    1. POST /api/mfa/enroll/start -> generate_enrollment_secret() creates
       a new base32 TOTP secret and stores it UNCONFIRMED (mfa_enabled
       stays false) on the subscriber row, and returns a provisioning
       URI the web app renders as a QR code for the person to scan.
    2. The person scans it with their authenticator app, which then
       produces a 6-digit code.
    3. POST /api/mfa/enroll/confirm -> confirm_enrollment() verifies that
       code against the stored secret; only on success does mfa_enabled
       flip to true. This proves the person actually has a working,
       correctly-time-synced authenticator before MFA is enforced on
       their account -- enabling MFA against a secret nobody can
       generate valid codes for would be a self-lockout bug, not a
       security feature.
    4. confirm_enrollment() also generates a set of one-time backup
       codes, returned to the person EXACTLY ONCE (only their hashes are
       stored, mirroring how passwords are never stored in plaintext)
       for account recovery if they lose their authenticator device.

Login-challenge flow (see api.handlers.login / login_mfa):

    1. POST /api/login with correct password, but mfa_enabled=true on
       the account, returns an `mfa_required` response with a short-lived
       challenge token INSTEAD OF a session token.
    2. POST /api/login/mfa with that challenge token plus a 6-digit TOTP
       code (or a backup code) verifies the code and, only on success,
       issues a real session via session_repo.create_session. A correct
       password alone is never sufficient to obtain a session once MFA
       is enabled -- see verify_mfa_code's docstring for how backup codes
       fit into this without weakening it.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Optional

import pyotp
from werkzeug.security import check_password_hash, generate_password_hash

from marketpulse.models.schemas import Subscriber
from marketpulse.persistence.subscriber_repo import SUBSCRIBERS_TABLE, _is_expired
from marketpulse.persistence.supabase_client import SupabaseClient, get_client

MFA_CHALLENGES_TABLE = "mfa_challenges"

ISSUER_NAME = "MarketPulse India"
NUM_BACKUP_CODES = 8
BACKUP_CODE_LENGTH = 10  # characters, alphanumeric -- typed manually if the authenticator app is unavailable


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

def generate_enrollment_secret(
    subscriber_id: str, account_label: str, client: Optional[SupabaseClient] = None
) -> dict:
    """
    Starts (or restarts) MFA enrollment: generates a fresh TOTP secret,
    stores it on the subscriber row WITHOUT enabling MFA yet, and returns
    both the raw secret (for manual entry) and a full `otpauth://`
    provisioning URI (for QR-code rendering client-side -- the web app
    generates the QR image itself; no secret-bearing image is ever
    rendered server-side or stored).

    `account_label` should be the subscriber's email or mobile number --
    whatever they'd recognize in their authenticator app's account list.
    """
    client = client or get_client()
    secret = pyotp.random_base32()
    client.update(
        SUBSCRIBERS_TABLE,
        params={"id": f"eq.{subscriber_id}"},
        patch={"mfa_secret": secret, "mfa_enabled": False, "mfa_backup_codes": []},
    )
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=account_label, issuer_name=ISSUER_NAME)
    return {"secret": secret, "provisioning_uri": uri}


def _generate_backup_codes() -> list:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # excludes ambiguous chars (0/O, 1/I/L)
    return ["".join(secrets.choice(alphabet) for _ in range(BACKUP_CODE_LENGTH)) for _ in range(NUM_BACKUP_CODES)]


def confirm_enrollment(
    subscriber_id: str, totp_code: str, client: Optional[SupabaseClient] = None
) -> Optional[list]:
    """
    Verifies the enrollment TOTP code against the secret stored by
    generate_enrollment_secret(). On success: flips mfa_enabled to true,
    generates a fresh set of backup codes, stores only their HASHES, and
    returns the PLAINTEXT codes -- the one and only time they are ever
    available in plaintext anywhere in the system, same handling as a
    password at creation time. Returns None if the code is wrong or no
    enrollment is in progress (no mfa_secret stored).
    """
    client = client or get_client()
    rows = client.select(SUBSCRIBERS_TABLE, params={"id": f"eq.{subscriber_id}"})
    if not rows or not rows[0].get("mfa_secret"):
        return None

    secret = rows[0]["mfa_secret"]
    if not pyotp.totp.TOTP(secret).verify(totp_code, valid_window=1):
        return None

    plaintext_codes = _generate_backup_codes()
    hashed_codes = [generate_password_hash(code) for code in plaintext_codes]

    client.update(
        SUBSCRIBERS_TABLE,
        params={"id": f"eq.{subscriber_id}"},
        patch={"mfa_enabled": True, "mfa_backup_codes": hashed_codes, "mfa_enrolled_at": _now_iso()},
    )
    return plaintext_codes


def disable_mfa(subscriber_id: str, client: Optional[SupabaseClient] = None) -> None:
    """Turns MFA off entirely and discards the secret + backup codes --
    re-enrollment afterward requires scanning a brand new QR code, by
    design, rather than reusing a secret that was ever disabled."""
    client = client or get_client()
    client.update(
        SUBSCRIBERS_TABLE,
        params={"id": f"eq.{subscriber_id}"},
        patch={"mfa_enabled": False, "mfa_secret": None, "mfa_backup_codes": [], "mfa_enrolled_at": None},
    )


def regenerate_backup_codes(subscriber_id: str, client: Optional[SupabaseClient] = None) -> Optional[list]:
    """Invalidates all existing backup codes and issues a fresh set --
    e.g. after the person suspects a backup code may have leaked, or has
    used most of them. Returns None if MFA isn't currently enabled (there
    is nothing to regenerate codes for)."""
    client = client or get_client()
    rows = client.select(SUBSCRIBERS_TABLE, params={"id": f"eq.{subscriber_id}"})
    if not rows or not rows[0].get("mfa_enabled"):
        return None

    plaintext_codes = _generate_backup_codes()
    hashed_codes = [generate_password_hash(code) for code in plaintext_codes]
    client.update(
        SUBSCRIBERS_TABLE,
        params={"id": f"eq.{subscriber_id}"},
        patch={"mfa_backup_codes": hashed_codes},
    )
    return plaintext_codes


# ---------------------------------------------------------------------------
# Verification (used by both the login challenge and any other
# re-auth-sensitive action that might want a step-up check later)
# ---------------------------------------------------------------------------

def verify_mfa_code(subscriber: Subscriber, code: str, client: Optional[SupabaseClient] = None) -> bool:
    """
    Verifies a 6-digit TOTP code OR a backup code against the
    subscriber's enrolled MFA state. A matched backup code is
    IMMEDIATELY CONSUMED (removed from the stored set) so it cannot be
    reused -- this is what keeps backup codes from quietly becoming a
    permanent second password; each one works exactly once.

    Returns False outright if MFA isn't enabled on this account (there is
    nothing valid to check against), rather than treating "no MFA
    configured" as an automatic pass -- callers must check
    subscriber.mfa_enabled themselves to decide whether MFA verification
    is required at all; this function only answers "does this code work."
    """
    if not subscriber.mfa_enabled or not subscriber.mfa_secret:
        return False

    code = (code or "").strip().replace(" ", "")

    if pyotp.totp.TOTP(subscriber.mfa_secret).verify(code, valid_window=1):
        return True

    # Not a valid TOTP code -- check backup codes. Hash the candidate
    # exactly once and compare against every stored hash; on match,
    # remove that one hash from the stored set (single-use).
    client = client or get_client()
    remaining_hashes = list(subscriber.mfa_backup_codes or [])
    for stored_hash in remaining_hashes:
        if check_password_hash(stored_hash, code):
            remaining_hashes.remove(stored_hash)
            client.update(
                SUBSCRIBERS_TABLE,
                params={"id": f"eq.{subscriber.id}"},
                patch={"mfa_backup_codes": remaining_hashes},
            )
            return True

    return False


# ---------------------------------------------------------------------------
# Login-challenge tokens (the bridge between "password correct" and
# "session issued" when MFA is enabled)
# ---------------------------------------------------------------------------

def create_mfa_challenge(subscriber_id: str, client: Optional[SupabaseClient] = None) -> str:
    """Issued by login() in place of a session token when the password
    was correct but MFA is enabled. Short-lived (5 minutes, schema.sql
    default) and single-use."""
    client = client or get_client()
    token = secrets.token_urlsafe(32)
    client.insert(
        MFA_CHALLENGES_TABLE,
        {"token": token, "subscriber_id": subscriber_id},
        return_row=False,
    )
    return token


def consume_mfa_challenge(token: str, client: Optional[SupabaseClient] = None) -> Optional[str]:
    """
    Validates and consumes an MFA challenge token, returning the
    associated subscriber_id on success or None if the token is
    missing/already-used/expired. Does NOT verify the TOTP/backup code
    itself -- that's verify_mfa_code's job; this function only confirms
    "yes, a password check for this account legitimately preceded this
    request a few minutes ago," which is what prevents someone from
    skipping straight to an MFA code submission with no valid password
    check behind it.
    """
    client = client or get_client()
    rows = client.select(MFA_CHALLENGES_TABLE, params={"token": f"eq.{token}"})
    if not rows or rows[0].get("consumed_at") or _is_expired(rows[0]):
        return None

    challenge = rows[0]
    client.update(
        MFA_CHALLENGES_TABLE,
        params={"token": f"eq.{token}"},
        patch={"consumed_at": _now_iso()},
    )
    return challenge["subscriber_id"]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
