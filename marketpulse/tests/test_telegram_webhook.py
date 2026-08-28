"""
tests/test_telegram_webhook.py

The Telegram webhook must reject POSTs that omit Telegram's secret-token
header. Spoofed /start payloads must never bind a chat_id.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marketpulse.delivery.telegram_sender import (
    expected_webhook_secret,
    telegram_webhook_authorized,
)


class TestTelegramWebhookSecret(unittest.TestCase):
    def test_explicit_secret_must_match(self):
        env = {"TELEGRAM_WEBHOOK_SECRET": "s3cret", "TELEGRAM_BOT_TOKEN": "bot-token"}
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(telegram_webhook_authorized("s3cret"))
            self.assertFalse(telegram_webhook_authorized("wrong"))
            self.assertFalse(telegram_webhook_authorized(""))
            self.assertFalse(telegram_webhook_authorized(None))

    def test_derived_secret_when_override_missing(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot-token"}, clear=True):
            derived = expected_webhook_secret()
            self.assertGreaterEqual(len(derived), 32)
            self.assertTrue(telegram_webhook_authorized(derived))
            self.assertFalse(telegram_webhook_authorized("bot-token"))

    def test_rejects_when_nothing_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(expected_webhook_secret(), "")
            self.assertFalse(telegram_webhook_authorized("anything"))


if __name__ == "__main__":
    unittest.main()
