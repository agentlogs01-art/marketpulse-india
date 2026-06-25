"""
persistence/supabase_client.py

Thin Supabase wrapper used by every repository module in this package.

Design choice: talk to Supabase's auto-generated PostgREST API directly
over HTTP via `requests`, rather than depending on the `supabase-py` SDK.
Reasons, consistent with the PRD's MVP philosophy of minimal moving
parts on a tight budget:

  - `requests` is already a project dependency (pipeline/market_data.py,
    pipeline/ingestion.py, ai_engine/llm_client.py all use it) -- no new
    dependency needed.
  - PostgREST's REST contract is small and stable; we only need
    select / insert / update / upsert, all of which map to one HTTP
    verb + query-string filter each.
  - Easier to unit-test: every network call goes through `_request`,
    which is trivial to monkeypatch/mock in tests.

All calls use the SERVICE ROLE key (server-side secret, never the anon
key) since this code runs in a trusted backend context (GitHub Actions /
Railway), not a browser. The service role key bypasses Row Level
Security by design -- see schema.sql for the RLS posture.
"""

from __future__ import annotations

import os
from typing import Any, Optional


class SupabaseConfigError(Exception):
    """Raised when required Supabase environment variables are missing."""


class SupabaseRequestError(Exception):
    """Raised when a Supabase PostgREST call returns a non-2xx response."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Supabase request failed ({status_code}): {message}")


class SupabaseClient:
    """
    Minimal PostgREST client: one instance per process, reused across
    repository calls. Reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
    from the environment (Railway / GitHub Actions secrets) by default,
    but both can be passed explicitly -- useful for tests.
    """

    def __init__(self, url: Optional[str] = None, service_role_key: Optional[str] = None):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = service_role_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

        if not self.url or not self.key:
            raise SupabaseConfigError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be set "
                "(directly or via environment variables) before using SupabaseClient."
            )

        self._rest_base = f"{self.url}/rest/v1"

    def _headers(self, prefer: Optional[str] = None) -> dict:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _request(
        self,
        method: str,
        table: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[Any] = None,
        prefer: Optional[str] = None,
        timeout: int = 10,
    ) -> Any:
        import requests  # local import: keeps module importable without network deps in tests

        url = f"{self._rest_base}/{table}"
        resp = requests.request(
            method,
            url,
            headers=self._headers(prefer=prefer),
            params=params,
            json=json_body,
            timeout=timeout,
        )
        if not (200 <= resp.status_code < 300):
            raise SupabaseRequestError(resp.status_code, resp.text)
        if resp.text:
            return resp.json()
        return None

    # -- Generic CRUD primitives used by the repository modules ----------

    def select(self, table: str, params: Optional[dict] = None) -> list:
        """
        `params` follows PostgREST filter syntax, e.g.
        {"status": "eq.active", "select": "email"}.
        """
        result = self._request("GET", table, params=params)
        return result or []

    def insert(self, table: str, row: dict, *, return_row: bool = True) -> Optional[dict]:
        prefer = "return=representation" if return_row else "return=minimal"
        result = self._request("POST", table, json_body=row, prefer=prefer)
        if return_row and result:
            return result[0]
        return None

    def upsert(self, table: str, row: dict, *, on_conflict: str, return_row: bool = True) -> Optional[dict]:
        prefer = "resolution=merge-duplicates"
        if return_row:
            prefer += ",return=representation"
        result = self._request(
            "POST",
            table,
            params={"on_conflict": on_conflict},
            json_body=row,
            prefer=prefer,
        )
        if return_row and result:
            return result[0]
        return None

    def update(self, table: str, params: dict, patch: dict, *, return_row: bool = False) -> Optional[list]:
        prefer = "return=representation" if return_row else "return=minimal"
        result = self._request("PATCH", table, params=params, json_body=patch, prefer=prefer)
        return result


_default_client: Optional[SupabaseClient] = None


def get_client() -> SupabaseClient:
    """
    Lazily construct and cache a single module-level SupabaseClient built
    from environment variables. Repository modules call this instead of
    constructing SupabaseClient() directly, so tests can monkeypatch
    `get_client` to inject a fake client without touching env vars.
    """
    global _default_client
    if _default_client is None:
        _default_client = SupabaseClient()
    return _default_client


def reset_default_client() -> None:
    """Test helper: force the next get_client() call to rebuild the client."""
    global _default_client
    _default_client = None
