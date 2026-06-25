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

SESSION_LIFETIME_DAYS = 30


def create_session(subscriber_id: str, client: Optional[SupabaseClient] = None) -> str:
    """Issues a new session token for a subscriber and returns it."""
    client = client or get_client()
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_LIFETIME_DAYS)).isoformat()
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
            if expiry < datetime.now(timezone.utc):
                return None
        except ValueError:
            pass  # malformed timestamp -- fail open rather than lock someone out on a parse quirk

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
