"""
tests/test_supabase_client.py

Tests the SupabaseClient wrapper's configuration handling and request
construction without making any real network calls -- the actual HTTP
call inside `_request` is monkeypatched via the `requests` module's
`request` function.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.persistence.supabase_client import (
    SupabaseClient,
    SupabaseConfigError,
    SupabaseRequestError,
)


class TestSupabaseClientConfig(unittest.TestCase):
    def test_raises_when_url_missing(self):
        with self.assertRaises(SupabaseConfigError):
            SupabaseClient(url="", service_role_key="key")

    def test_raises_when_key_missing(self):
        with self.assertRaises(SupabaseConfigError):
            SupabaseClient(url="https://example.supabase.co", service_role_key="")

    def test_strips_trailing_slash_from_url(self):
        client = SupabaseClient(url="https://example.supabase.co/", service_role_key="key")
        self.assertEqual(client.url, "https://example.supabase.co")
        self.assertEqual(client._rest_base, "https://example.supabase.co/rest/v1")

    def test_headers_include_service_role_key(self):
        client = SupabaseClient(url="https://example.supabase.co", service_role_key="my-secret")
        headers = client._headers()
        self.assertEqual(headers["apikey"], "my-secret")
        self.assertEqual(headers["Authorization"], "Bearer my-secret")

    def test_headers_include_prefer_when_given(self):
        client = SupabaseClient(url="https://example.supabase.co", service_role_key="key")
        headers = client._headers(prefer="return=representation")
        self.assertEqual(headers["Prefer"], "return=representation")


class TestSupabaseClientRequests(unittest.TestCase):
    def setUp(self):
        self.client = SupabaseClient(url="https://example.supabase.co", service_role_key="key")

    @patch("requests.request")
    def test_select_calls_get_with_params(self, mock_request):
        mock_response = MagicMock(status_code=200, text='[{"email": "a@example.com"}]')
        mock_response.json.return_value = [{"email": "a@example.com"}]
        mock_request.return_value = mock_response

        result = self.client.select("subscribers", params={"status": "eq.active"})

        self.assertEqual(result, [{"email": "a@example.com"}])
        called_args, called_kwargs = mock_request.call_args
        self.assertEqual(called_args[0], "GET")
        self.assertIn("/rest/v1/subscribers", called_args[1])
        self.assertEqual(called_kwargs["params"], {"status": "eq.active"})

    @patch("requests.request")
    def test_non_2xx_raises_supabase_request_error(self, mock_request):
        mock_response = MagicMock(status_code=400, text="bad request")
        mock_request.return_value = mock_response

        with self.assertRaises(SupabaseRequestError) as ctx:
            self.client.select("subscribers")
        self.assertEqual(ctx.exception.status_code, 400)

    @patch("requests.request")
    def test_insert_returns_first_row_when_return_row_true(self, mock_request):
        mock_response = MagicMock(status_code=201, text='[{"id": "1", "email": "a@example.com"}]')
        mock_response.json.return_value = [{"id": "1", "email": "a@example.com"}]
        mock_request.return_value = mock_response

        result = self.client.insert("subscribers", {"email": "a@example.com"})
        self.assertEqual(result["id"], "1")

    @patch("requests.request")
    def test_insert_returns_none_when_return_row_false(self, mock_request):
        mock_response = MagicMock(status_code=201, text="")
        mock_request.return_value = mock_response

        result = self.client.insert("subscribers", {"email": "a@example.com"}, return_row=False)
        self.assertIsNone(result)

    @patch("requests.request")
    def test_upsert_sets_on_conflict_param_and_merge_prefer(self, mock_request):
        mock_response = MagicMock(status_code=200, text='[{"trade_date": "2026-06-19"}]')
        mock_response.json.return_value = [{"trade_date": "2026-06-19"}]
        mock_request.return_value = mock_response

        self.client.upsert("market_closes", {"trade_date": "2026-06-19"}, on_conflict="trade_date")

        called_args, called_kwargs = mock_request.call_args
        self.assertEqual(called_kwargs["params"], {"on_conflict": "trade_date"})
        self.assertIn("resolution=merge-duplicates", called_kwargs["headers"]["Prefer"])


if __name__ == "__main__":
    unittest.main()
