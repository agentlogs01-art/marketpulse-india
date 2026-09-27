"""
persistence/session_repo.py

Repository for the `sessions` table. A session token is issued at login
(api.handlers.login) and is what the website's dashboard sends back on
every subsequent request to prove who's asking -- this is the whole
mechanism behind "sign in once, then view the briefing without
re-entering credentials."

Tokens are opaque random strings (not JWTs) deliberately: the MVP has no
need for a stateless/self-contained token, and a DB-backed session means
logout (revoke) and "sign out everywhere" are a single UPDATE rather than
needing a token blocklist. At MVP subscriber volumes the extra lookup per
request costs nothing meaningful.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from marketpulse.persistence.supabase_client import SupabaseClient, get_client

TABLE = "sessions"

# Hard cap if a session is never used; activity slides this window.
SESSION_LIFETIME_DAYS = 30
# Sign-out after this much idle time (no authenticated API calls).
IDLE_TIMEOUT_MINUTES = 30


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _idle_expiry() -> datetime:
    return _utc_now() + timedelta(minutes=IDLE_TIMEOUT_MINUTES)


def create_session(subscriber_id: str, client: Optional[SupabaseClient] = None) -> str:
    """Issues a new session token for a subscriber and returns it."""
    client = client or get_client()
    token = secrets.token_urlsafe(32)
    expires_at = _idle_expiry().isoformat()
    client.insert(
        TABLE,
        {"token": token, "subscriber_id": subscriber_id, "expires_at": expires_at},
        return_row=False,
    )
    return token


def get_subscriber_id_for_token(token: str, client: Optional[SupabaseClient] = None) -> Optional[str]:
    """
    Resolves a session token to a subscriber_id, or None if the token is
    missing, revoked, or expired. This is the function every
    authenticated API route calls before doing anything else.
    """
    if not token:
        return None
    client = client or get_client()
    rows = client.select(TABLE, params={"token": f"eq.{token}"})
    if not rows:
        return None

    session = rows[0]
    if session.get("revoked_at"):
        return None

    expires_at = session.get("expires_at")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry < _utc_now():
                return None
        except ValueError:
            pass  # malformed timestamp -- fail open rather than lock someone out on a parse quirk

    created_at = session.get("created_at")
    if created_at:
        try:
            created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created + timedelta(days=SESSION_LIFETIME_DAYS) < _utc_now():
                return None
        except ValueError:
            pass

    try:
        client.update(
            TABLE,
            params={"token": f"eq.{token}"},
            patch={"expires_at": _idle_expiry().isoformat()},
        )
    except Exception:
        pass

    return session["subscriber_id"]


def revoke_session(token: str, client: Optional[SupabaseClient] = None) -> None:
    """Logs out a single session (the one the request came in on)."""
    client = client or get_client()
    client.update(
        TABLE,
        params={"token": f"eq.{token}"},
        patch={"revoked_at": datetime.now(timezone.utc).isoformat()},
    )


def revoke_all_sessions_for_subscriber(subscriber_id: str, client: Optional[SupabaseClient] = None) -> None:
    """'Sign out everywhere' -- e.g. after a password change."""
    client = client or get_client()
    client.update(
        TABLE,
        params={"subscriber_id": f"eq.{subscriber_id}"},
        patch={"revoked_at": datetime.now(timezone.utc).isoformat()},
    )
