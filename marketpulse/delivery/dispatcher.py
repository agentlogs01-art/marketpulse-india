"""
delivery/dispatcher.py

Fans out one day's pipeline_output to every active subscriber across
all three channels (Email, WhatsApp, Telegram). This replaces the
email-only call in scheduler/run_daily_briefing.py with a multi-channel
equivalent, while keeping the same defensive posture: a failure on one
channel, or for one subscriber, never blocks delivery to anyone else.

Email continues to be sent as a single batched call (email_system.sender
.send_email already accepts a list of recipients and a single SMTP
session); WhatsApp and Telegram are inherently per-recipient APIs, so
those two are dispatched in a loop with per-subscriber error capture.
"""

from __future__ import annotations

from marketpulse.delivery.text_render import render_plain_text, render_telegram_markdown
from marketpulse.models.schemas import DeliveryChannel


def dispatch_all_channels(pipeline_output: dict, subject: str, html: str) -> dict:
    """
    Sends today's briefing across every channel with at least one active
    subscriber. Returns a per-channel result dict:

        {
          "email":    {"sent": [...], "failed": [...], "total": N} | None,
          "whatsapp": {"sent": [...], "failed": [...], "total": N},
          "telegram": {"sent": [...], "failed": [...], "total": N},
        }

    A channel key is omitted (None) if it was never attempted (e.g. no
    SMTP creds configured and no Supabase, or no subscribers found for
    that channel) -- this lets the caller distinguish "nobody to send to"
    from "tried and failed."
    """
    results: dict = {"email": None, "whatsapp": None, "telegram": None}

    results["email"] = _dispatch_email(subject, html)
    results["whatsapp"] = _dispatch_whatsapp(pipeline_output)
    results["telegram"] = _dispatch_telegram(pipeline_output)

    return results


def _dispatch_email(subject: str, html: str) -> dict:
    from marketpulse.email_system.sender import EmailSendError, load_subscriber_list, send_email

    recipients = load_subscriber_list()
    if not recipients:
        return {"sent": [], "failed": [], "total": 0}
    try:
        return send_email(subject, html, recipients)
    except EmailSendError as exc:
        return {"sent": [], "failed": [{"address": "ALL", "error": str(exc)}], "total": len(recipients)}


def _dispatch_whatsapp(pipeline_output: dict) -> dict:
    from marketpulse.delivery.whatsapp_sender import WhatsAppSendError, send_briefing_to_subscriber
    from marketpulse.persistence.subscriber_repo import list_active_subscribers_for_channel

    try:
        subscribers = list_active_subscribers_for_channel(DeliveryChannel.WHATSAPP)
    except Exception:
        return {"sent": [], "failed": [], "total": 0}

    if not subscribers:
        return {"sent": [], "failed": [], "total": 0}

    text = render_plain_text(pipeline_output)
    sent, failed = [], []
    for subscriber in subscribers:
        try:
            send_briefing_to_subscriber(subscriber.whatsapp_number, text)
            sent.append(subscriber.whatsapp_number)
        except WhatsAppSendError as exc:
            failed.append({"address": subscriber.whatsapp_number, "error": str(exc)})
    return {"sent": sent, "failed": failed, "total": len(subscribers)}


def _dispatch_telegram(pipeline_output: dict) -> dict:
    from marketpulse.delivery.telegram_sender import TelegramSendError, send_briefing_to_subscriber
    from marketpulse.persistence.subscriber_repo import list_active_subscribers_for_channel

    try:
        subscribers = list_active_subscribers_for_channel(DeliveryChannel.TELEGRAM)
    except Exception:
        return {"sent": [], "failed": [], "total": 0}

    if not subscribers:
        return {"sent": [], "failed": [], "total": 0}

    markdown_text = render_telegram_markdown(pipeline_output)
    sent, failed = [], []
    for subscriber in subscribers:
        try:
            send_briefing_to_subscriber(subscriber.telegram_chat_id, markdown_text)
            sent.append(subscriber.telegram_chat_id)
        except TelegramSendError as exc:
            failed.append({"address": subscriber.telegram_chat_id, "error": str(exc)})
    return {"sent": sent, "failed": failed, "total": len(subscribers)}


def flatten_results_for_audit(results: dict) -> tuple:
    """
    Collapses the per-channel results dict into the (sent, failed) shape
    persistence.run_log_repo.record_send_results expects, tagging each
    entry with its channel so the send_log table's `channel` column gets
    populated correctly.
    """
    sent: list = []
    failed: list = []
    for channel, result in results.items():
        if not result:
            continue
        for address in result.get("sent", []):
            sent.append({"address": address, "channel": channel})
        for failure in result.get("failed", []):
            failed.append({"address": failure["address"], "error": failure.get("error"), "channel": channel})
    return sent, failed
