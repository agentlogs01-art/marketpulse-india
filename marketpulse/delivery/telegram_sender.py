"""
delivery/telegram_sender.py

Telegram delivery channel. Uses the Telegram Bot API directly over HTTP
(api.telegram.org) -- no SDK dependency, consistent with the project's
"requests is the only HTTP dependency" approach. The Bot API is entirely
free with no rate-limit cost concerns at MVP subscriber volumes (Telegram
allows ~30 messages/second per bot).

Two responsibilities:
  1. send_briefing_to_subscriber() -- push today's digest to a bound
     chat_id (called by delivery/dispatcher.py during the 06:50-07:00
     IST send step).
  2. handle_start_command() -- process an incoming `/start <link_code>`
     update from Telegram's webhook, binding chat_id to the right
     subscriber via persistence/subscriber_repo.consume_telegram_link.

Webhook setup (one-time, manual step, not automated here): point
Telegram at this bot's webhook URL via
    https://api.telegram.org/bot<TOKEN>/setWebhook?url=<your-endpoint>
where <your-endpoint> routes incoming updates to handle_start_command().
"""

from __future__ import annotations

import os
from typing import Optional

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramSendError(Exception):
    pass


def _bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramSendError("TELEGRAM_BOT_TOKEN not set in environment")
    return token


def build_deep_link(link_code: str, bot_username: Optional[str] = None) -> str:
    """
    Builds the https://t.me/<bot>?start=<code> deep-link the web app
    shows/emails to the person during signup. Tapping it opens Telegram
    with the bot's chat pre-loaded and automatically sends
    `/start <link_code>` once they hit "Start".
    """
    bot_username = bot_username or os.environ.get("TELEGRAM_BOT_USERNAME", "MarketPulseIndiaBot")
    return f"https://t.me/{bot_username}?start={link_code}"


def send_message(chat_id: str, text: str, parse_mode: Optional[str] = "MarkdownV2") -> dict:
    """
    Sends a single message via the Bot API's sendMessage method.
    `parse_mode` should match how `text` was formatted -- pass None for
    delivery/text_render.render_plain_text() output, "MarkdownV2" for
    delivery/text_render.render_telegram_markdown() output.
    """
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
    """
    Sends the rendered briefing to one subscriber's bound Telegram chat.
    Falls back to plain text (no parse_mode) if the MarkdownV2 send fails
    -- a single unescaped character in upstream content could otherwise
    cause Telegram to reject the whole message, and a malformed digest is
    better than a missed one.
    """
    try:
        return send_message(chat_id, markdown_text, parse_mode="MarkdownV2")
    except TelegramSendError:
        plain_fallback = markdown_text.replace("\\", "").replace("*", "").replace("_", "")
        return send_message(chat_id, plain_fallback, parse_mode=None)


def handle_start_command(update: dict) -> Optional[dict]:
    """
    Processes a Telegram webhook `update` object for a `/start <code>`
    message. Returns the bound Subscriber row (or None if the link_code
    was invalid/expired/already used) -- the webhook endpoint (api/) uses
    this to decide what confirmation message, if any, to send back.

    Expected update shape (Telegram Bot API "Update" object):
        {"message": {"text": "/start abc123", "chat": {"id": 123456789}}}
    """
    from datetime import datetime, timezone

    from marketpulse.persistence.subscriber_repo import consume_telegram_link

    message = update.get("message", {})
    text = message.get("text", "")
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if not text.startswith("/start") or not chat_id:
        return None

    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    link_code = parts[1].strip()

    subscriber = consume_telegram_link(
        link_code, chat_id, datetime.now(timezone.utc).isoformat()
    )
    return subscriber.__dict__ if subscriber else None
