"""
tests/test_persistence.py

Tests every repository module against a FakeSupabaseClient -- an
in-memory stand-in implementing the same select/insert/upsert/update
surface as persistence/supabase_client.SupabaseClient, so these tests
run with zero network access and zero real Supabase project required.

This validates the repository logic (filter construction, idempotency
via on_conflict, row shaping) independent of whether the real
PostgREST HTTP layer works -- that layer is exercised by hand against a
real Supabase project, not by automated tests, since it's a thin pass-
through with no business logic of its own.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.models.schemas import PipelineRunRecord
from marketpulse.persistence import market_close_repo, run_log_repo, subscriber_repo


class FakeSupabaseClient:
    """
    Minimal in-memory emulation of PostgREST semantics needed by the
    repository modules: eq./order/limit filters on select, and
    on_conflict-based upsert. Good enough to test repo-level logic
    without a real database.
    """

    def __init__(self):
        self.tables = {}

    def _table(self, name):
        return self.tables.setdefault(name, [])

    @staticmethod
    def _matches(row, params):
        for key, value in params.items():
            if key in ("select", "order", "limit", "on_conflict"):
                continue
            if not isinstance(value, str) or not value.startswith("eq."):
                continue
            target = value[len("eq."):]
            if str(row.get(key)) != target:
                return False
        return True

    def select(self, table, params=None):
        params = params or {}
        rows = [r for r in self._table(table) if self._matches(r, params)]

        order = params.get("order")
        if order:
            field, _, direction = order.partition(".")
            rows = sorted(rows, key=lambda r: r.get(field), reverse=(direction == "desc"))

        limit = params.get("limit")
        if limit:
            rows = rows[: int(limit)]

        select_fields = params.get("select")
        if select_fields and select_fields != "*":
            fields = select_fields.split(",")
            rows = [{f: r.get(f) for f in fields} for r in rows]

        return [dict(r) for r in rows]

    def insert(self, table, row, *, return_row=True):
        stored = dict(row)
        stored.setdefault("id", f"fake-id-{len(self._table(table)) + 1}")
        self._table(table).append(stored)
        return dict(stored) if return_row else None

    def upsert(self, table, row, *, on_conflict, return_row=True):
        rows = self._table(table)
        for existing in rows:
            if existing.get(on_conflict) == row.get(on_conflict):
                existing.update(row)
                return dict(existing) if return_row else None
        stored = dict(row)
        stored.setdefault("id", f"fake-id-{len(rows) + 1}")
        rows.append(stored)
        return dict(stored) if return_row else None

    def update(self, table, params, patch, *, return_row=False):
        updated = []
        for row in self._table(table):
            if self._matches(row, params):
                row.update(patch)
                updated.append(dict(row))
        return updated if return_row else None


class TestSubscriberRepo(unittest.TestCase):
    def setUp(self):
        self.client = FakeSupabaseClient()

    def test_add_and_list_active_subscribers(self):
        subscriber_repo.add_subscriber("a@example.com", client=self.client)
        subscriber_repo.add_subscriber("b@example.com", client=self.client)
        emails = subscriber_repo.list_active_subscriber_emails(client=self.client)
        self.assertEqual(set(emails), {"a@example.com", "b@example.com"})

    def test_add_subscriber_is_idempotent(self):
        subscriber_repo.add_subscriber("a@example.com", client=self.client)
        subscriber_repo.add_subscriber("a@example.com", client=self.client)
        rows = self.client.select(subscriber_repo.TABLE)
        self.assertEqual(len(rows), 1)

    def test_unsubscribe_excludes_from_active_list(self):
        subscriber_repo.add_subscriber("a@example.com", client=self.client)
        subscriber_repo.unsubscribe("a@example.com", "2026-06-20T10:00:00Z", client=self.client)
        emails = subscriber_repo.list_active_subscriber_emails(client=self.client)
        self.assertEqual(emails, [])

    def test_pause_and_reactivate(self):
        subscriber_repo.add_subscriber("a@example.com", client=self.client)
        subscriber_repo.pause_subscriber("a@example.com", client=self.client)
        self.assertEqual(subscriber_repo.list_active_subscriber_emails(client=self.client), [])
        subscriber_repo.reactivate_subscriber("a@example.com", client=self.client)
        self.assertEqual(subscriber_repo.list_active_subscriber_emails(client=self.client), ["a@example.com"])


class TestMarketCloseRepo(unittest.TestCase):
    def setUp(self):
        self.client = FakeSupabaseClient()

    def test_record_and_get_close(self):
        market_close_repo.record_close("2026-06-19", 24838.20, client=self.client)
        value = market_close_repo.get_close("2026-06-19", client=self.client)
        self.assertEqual(value, 24838.20)

    def test_record_close_is_idempotent_per_date(self):
        market_close_repo.record_close("2026-06-19", 24838.20, client=self.client)
        market_close_repo.record_close("2026-06-19", 24900.00, client=self.client)
        rows = self.client.select(market_close_repo.TABLE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nifty_close"], 24900.00)

    def test_get_latest_close_picks_most_recent(self):
        market_close_repo.record_close("2026-06-18", 24700.0, client=self.client)
        market_close_repo.record_close("2026-06-19", 24838.20, client=self.client)
        latest = market_close_repo.get_latest_close(client=self.client)
        self.assertEqual(latest["trade_date"], "2026-06-19")

    def test_get_close_returns_none_when_missing(self):
        value = market_close_repo.get_close("2026-01-01", client=self.client)
        self.assertIsNone(value)


class TestRunLogRepo(unittest.TestCase):
    def setUp(self):
        self.client = FakeSupabaseClient()

    def test_record_pipeline_run_upserts_on_date(self):
        record = PipelineRunRecord(run_date_ist="2026-06-20", flat_override_triggered=True)
        run_log_repo.record_pipeline_run(record, bias_label="FLAT", gift_nifty_pct_change=0.05, client=self.client)
        run_log_repo.record_pipeline_run(record, bias_label="FLAT", gift_nifty_pct_change=0.07, client=self.client)
        rows = self.client.select(run_log_repo.RUNS_TABLE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["gift_nifty_pct_change"], 0.07)

    def test_record_send_results_creates_one_row_per_recipient(self):
        record = PipelineRunRecord(run_date_ist="2026-06-20")
        run_row = run_log_repo.record_pipeline_run(record, client=self.client)
        run_log_repo.record_send_results(
            run_row["id"],
            sent=["a@example.com", "b@example.com"],
            failed=[{"address": "c@example.com", "error": "bounced"}],
            client=self.client,
        )
        rows = self.client.select(run_log_repo.SEND_LOG_TABLE)
        self.assertEqual(len(rows), 3)
        statuses = {r["recipient_email"]: r["status"] for r in rows}
        self.assertEqual(statuses["a@example.com"], "sent")
        self.assertEqual(statuses["c@example.com"], "failed")

    def test_get_run_by_date(self):
        record = PipelineRunRecord(run_date_ist="2026-06-20")
        run_log_repo.record_pipeline_run(record, client=self.client)
        found = run_log_repo.get_run_by_date("2026-06-20", client=self.client)
        self.assertIsNotNone(found)
        self.assertEqual(found["run_date_ist"], "2026-06-20")

    def test_get_run_history_orders_newest_first(self):
        for date in ["2026-06-18", "2026-06-19", "2026-06-20"]:
            run_log_repo.record_pipeline_run(PipelineRunRecord(run_date_ist=date), client=self.client)
        history = run_log_repo.get_run_history(limit=2, client=self.client)
        self.assertEqual([r["run_date_ist"] for r in history], ["2026-06-20", "2026-06-19"])


if __name__ == "__main__":
    unittest.main()
