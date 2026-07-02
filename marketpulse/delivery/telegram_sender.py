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

from typing import Optional
from datetime import datetime, timezone
import logging

# Set up logging so you can see failures in your server console
logger = logging.getLogger(__name__)

def handle_start_command(update: dict) -> Optional[dict]:
    """
    Processes a Telegram webhook `update` object for a `/start <code>`
    message. Returns the bound Subscriber row (or None if the link_code
    was invalid/expired/already used).
    """
    from marketpulse.persistence.subscriber_repo import consume_telegram_link

    # 1. Extract payload safely
    message = update.get("message", {})
    text = message.get("text", "")
    chat = message.get("chat", {})
    
    # Check data type matching: keeps it as an integer if your DB expects a BIGINT number, 
    # but change to str(chat.get("id", "")) if your DB column is explicitly a string text type.
    chat_id = chat.get("id") 

    if not text.startswith("/start") or not chat_id:
        return None

    # 2. Separate command from token code
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    link_code = parts[1].strip()

    logger.info(f"Processing link verification: Code={link_code} for ChatID={chat_id}")

    try:
        # 3. Fire your repository state update
        subscriber = consume_telegram_link(
            link_code, chat_id, datetime.now(timezone.utc).isoformat()
        )
        
        if subscriber:
            logger.info(f"Successfully linked Telegram account to subscriber: {subscriber.id}")
            return subscriber.__dict__
        else:
            logger.warning(f"Link failed: Code {link_code} may be expired, invalid, or already claimed.")
            return None
            
    except Exception as e:
        logger.error(f"Database constraint or execution error in consume_telegram_link: {str(e)}", exc_info=True)
        return None

def handle_start_command1(update):
    """
    Parses incoming Telegram webhook payloads for a /start command containing 
    a subscriber deep-link token, saves the chat_id, and returns the updated record dict.
    """
    # 1. Safely navigate the structural Telegram payload nesting
    message = update.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text", "").strip()

    if not chat_id or not text.startswith("/start"):
        return None

    # 2. Extract the deep link token parameter string
    # If text is "/start WDjh2LsoxmKycfu9PFcUHw", splitting by whitespace gives us the token
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None  # Plain /start clicked without a linkage token
        
    link_code = parts[1].strip()

    # 3. Connect to your database engine and execute the update query
    # (Adapt the exact ORM/SQL execution framework used across your app)
    from marketpulse.db import get_db_connection  # Example database connection import
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Look up the profile matching the dynamic token link string
            # and populate the respective telegram_chat_id parameter slot
            cur.execute(
                """
                UPDATE subscribers 
                SET telegram_chat_id = %s, updated_at = NOW() 
                WHERE telegram_link_code = %s 
                RETURNING id, email, telegram_chat_id;
                """,
                (chat_id, link_code)
            )
            updated_row = cur.fetchone()
            if updated_row:
                conn.commit()
                return dict(updated_row)

    return None
