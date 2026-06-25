"""
delivery/whatsapp_sender.py

WhatsApp delivery channel via Twilio's WhatsApp Business API. Uses
Twilio's REST API directly over HTTP (no `twilio` SDK dependency,
consistent with the "requests is the only HTTP dependency" approach
used everywhere else in this project) -- Twilio's REST contract for
sending a message is one POST with basic auth, well within what's
reasonable to hand-roll.

Cost note for the PRD's infra budget (Section 3, $16-26/mo): Twilio's
WhatsApp Sandbox is free for development/testing (the recipient must
first send the sandbox's join code once). Production WhatsApp Business
sending requires Meta's WhatsApp Business Platform approval and has a
small per-conversation cost (roughly $0.0014-0.08 depending on
country/category) -- at MVP subscriber volumes (dozens, not thousands)
this stays well inside the existing budget. This module works
identically against the sandbox or a production WhatsApp Business
number; only the `TWILIO_WHATSAPP_FROM` env var changes.

WhatsApp's "session" messaging rules (Meta policy, not something this
code can route around): a business can only message a user freely
within 24 hours of that user's last message to the business, OR by
using a pre-approved message Template outside that window. A daily
pre-market briefing is exactly the case that needs a Template -- see
WHATSAPP_TEMPLATE_NOTE below.
"""

from __future__ import annotations

import os
from typing import Optional

WHATSAPP_TEMPLATE_NOTE = """\
WhatsApp Business Platform requires pre-approved Message Templates for
any business-initiated message sent outside a 24-hour customer-service
window (Meta policy, not a Twilio or MarketPulse India limitation). A
daily 07:00 IST briefing the subscriber didn't just message about falls
outside that window every single day, so in production this module
should send a Template (via Twilio's Content API / template SID) rather
than a free-form body. For the MVP/sandbox, free-form sends work because
the sandbox doesn't enforce the 24-hour window the same way -- this is
flagged here so it isn't missed when moving off the sandbox.
"""


class WhatsAppSendError(Exception):
    pass


def _twilio_credentials() -> tuple:
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_WHATSAPP_FROM")  # e.g. "whatsapp:+14155238886"

    if not all([account_sid, auth_token, from_number]):
        raise WhatsAppSendError(
            "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_WHATSAPP_FROM "
            "must all be set in the environment"
        )
    return account_sid, auth_token, from_number


def send_whatsapp_message(
    to_number: str,
    body: str,
    content_sid: Optional[str] = None,
    content_variables: Optional[dict] = None,
) -> dict:
    """
    Sends a WhatsApp message via Twilio.

    For a one-off free-form message (sandbox / within a live 24h customer
    session), pass `body` only. For a production daily briefing using an
    approved Template (see WHATSAPP_TEMPLATE_NOTE), pass `content_sid`
    (the Twilio Content API template SID) and `content_variables` (a
    dict of template placeholder values) instead -- Twilio ignores `body`
    when `content_sid` is supplied.

    `to_number` must be E.164 format (e.g. "+919876543210"); this
    function prefixes it with the required "whatsapp:" scheme.
    """
    import requests

    account_sid, auth_token, from_number = _twilio_credentials()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

    to_whatsapp = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"

    payload = {"From": from_number, "To": to_whatsapp}
    if content_sid:
        import json

        payload["ContentSid"] = content_sid
        if content_variables:
            payload["ContentVariables"] = json.dumps(content_variables)
    else:
        payload["Body"] = body

    resp = requests.post(url, data=payload, auth=(account_sid, auth_token), timeout=10)
    if resp.status_code not in (200, 201):
        raise WhatsAppSendError(f"Twilio WhatsApp send failed ({resp.status_code}): {resp.text}")
    return resp.json()


def send_briefing_to_subscriber(whatsapp_number: str, plain_text: str) -> dict:
    """
    Sends today's plain-text briefing (delivery.text_render.render_plain_text
    output) to one subscriber's WhatsApp number. Twilio caps a single
    message body at 1600 characters; longer content is split into
    sequential messages rather than truncated, so nothing is silently
    dropped from the briefing.
    """
    chunks = _split_into_whatsapp_chunks(plain_text)
    results = []
    for chunk in chunks:
        results.append(send_whatsapp_message(whatsapp_number, chunk))
    return {"message_count": len(results), "sids": [r.get("sid") for r in results]}


def _split_into_whatsapp_chunks(text: str, max_len: int = 1500) -> list:
    """Splits on blank-line boundaries where possible, to avoid breaking
    mid-sentence; falls back to a hard cut only if a single section
    exceeds max_len (shouldn't happen with the current template)."""
    sections = text.split("\n\n")
    chunks: list = []
    current = ""
    for section in sections:
        candidate = f"{current}\n\n{section}" if current else section
        if len(candidate) > max_len and current:
            chunks.append(current)
            current = section
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [text[:max_len]]
