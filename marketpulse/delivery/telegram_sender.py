"""
delivery/telegram_sender.py

Telegram Bot API over HTTP (no SDK). Two jobs:

  1. send_briefing_to_subscriber() -- 07:00 IST digest to a bound chat_id
  2. handle_start_command() -- `/start <link_code>` from the webhook

Webhook registration must include a secret_token. Telegram then sends it
on every update as X-Telegram-Bot-Api-Secret-Token. Without that check,
anyone who knows the public URL can POST fake /start payloads.

Register (once) after deploy:

    python -c "from marketpulse.delivery.telegram_sender import register_webhook; print(register_webhook())"

or:

    curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \\
      -d url="$WEBAPP_BASE_URL/api/telegram/webhook" \\
      -d secret_token="$TELEGRAM_WEBHOOK_SECRET"
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_WEBHOOK_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class TelegramSendError(Exception):
    pass


def _bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramSendError("TELEGRAM_BOT_TOKEN not set in environment")
    return token


def expected_webhook_secret() -> str:
    """
    Prefer TELEGRAM_WEBHOOK_SECRET. If unset, derive a stable secret from
    the bot token so production can register a webhook without a second
    secret, while still rejecting unauthenticated POSTs.
    """
    explicit = (os.environ.get("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if explicit:
        return explicit
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return ""
    return hashlib.sha256(f"marketpulse-tg-webhook:{token}".encode("utf-8")).hexdigest()


def telegram_webhook_authorized(header_value: Optional[str]) -> bool:
    expected = expected_webhook_secret()
    if not expected:
        return False
    provided = (header_value or "").strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


def register_webhook(public_base_url: Optional[str] = None) -> dict:
    """Point Telegram at this app's webhook with secret_token set."""
    import requests

    base = (public_base_url or os.environ.get("WEBAPP_BASE_URL") or "").rstrip("/")
    if not base:
        raise TelegramSendError("WEBAPP_BASE_URL is required to register the Telegram webhook")
    secret = expected_webhook_secret()
    if not secret:
        raise TelegramSendError("Set TELEGRAM_BOT_TOKEN or TELEGRAM_WEBHOOK_SECRET first")
    hook_url = f"{base}/api/telegram/webhook"
    resp = requests.post(
        f"{TELEGRAM_API_BASE}/bot{_bot_token()}/setWebhook",
        json={
            "url": hook_url,
            "secret_token": secret,
            "allowed_updates": ["message"],
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise TelegramSendError(f"setWebhook failed ({resp.status_code}): {resp.text}")
    return resp.json()


def build_deep_link(link_code: str, bot_username: Optional[str] = None) -> str:
    bot_username = bot_username or os.environ.get("TELEGRAM_BOT_USERNAME", "MarketPulseIndiaBot")
    return f"https://t.me/{bot_username}?start={link_code}"


def send_message(chat_id: str, text: str, parse_mode: Optional[str] = "MarkdownV2") -> dict:
    import requests

    url = f"{TELEGRAM_API_BASE}/bot{_bot_token()}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    resp = requests.post(url, json=payload, timeout=10)
    if resp.status_code != 200:
        raise TelegramSendError(f"Telegram sendMessage failed ({resp.status_code}): {resp.text}")
    return resp.json()


def send_briefing_to_subscriber(chat_id: str, markdown_text: str) -> dict:
    try:
        return send_message(chat_id, markdown_text, parse_mode="MarkdownV2")
    except TelegramSendError:
        plain_fallback = markdown_text.replace("\\", "").replace("*", "").replace("_", "")
        return send_message(chat_id, plain_fallback, parse_mode=None)


def handle_start_command(update: dict) -> Optional[dict]:
    """
    Processes a Telegram webhook `update` for `/start <code>`.
    Returns the bound Subscriber as a dict, or None if the code is invalid.
    """
    from marketpulse.persistence.subscriber_repo import consume_telegram_link

    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not text.startswith("/start") or chat_id is None:
        return None

    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    link_code = parts[1].strip()

    logger.info("Processing Telegram link code for chat_id=%s", chat_id)

    try:
        subscriber = consume_telegram_link(
            link_code, str(chat_id), datetime.now(timezone.utc).isoformat()
        )
        if subscriber:
            logger.info("Linked Telegram chat to subscriber %s", subscriber.id)
            return subscriber.__dict__
        logger.warning("Telegram link_code invalid, expired, or already used")
        return None
    except Exception as exc:
        logger.error("consume_telegram_link failed: %s", exc, exc_info=True)
        return None
