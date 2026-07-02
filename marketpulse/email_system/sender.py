"""
email_system/sender.py

Dispatches the rendered HTML email to the subscriber list. Uses plain
SMTP (e.g. a free-tier transactional provider like Brevo/SendGrid free
tier, or Gmail SMTP for very low volume) to stay within the PRD's
$16-26/month total infra budget (Section 3) -- no dedicated paid email
platform in the MVP.

Credentials are read from environment variables (Railway env vars),
never hardcoded.
"""

from __future__ import annotations

import os
import os
import requests
from typing import List, Dict, Any    
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class EmailSendError(Exception):
    pass

def _build_message(subject: str, html_body: str, from_addr: str, to_addr: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    plain_fallback = (
        "This email requires HTML to display properly. "
        "Please view in a client that supports HTML email, "
        "or visit your MarketPulse India web dashboard."
    )
    msg.attach(MIMEText(plain_fallback, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    return msg

def send_email(subject: str, html_body: str, to_addrs: list) -> dict:
    """
    Send the briefing to a list of subscriber addresses via Brevo's HTTP API.
    Returns a result dict with per-recipient success/failure so GitHub Actions 
    runners never crash over network/IP blocks or a single bad email.
    """
    # Brevo requires the Master API key (starts with xkeysib-)
    api_key = os.environ.get("BREVO_API_KEY") or os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("EMAIL_FROM_ADDRESS", "agentlogs01@gmail.com")

    if not api_key:
        raise EmailSendError("Brevo API Key (BREVO_API_KEY or SMTP_PASSWORD) missing in environment.")

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": api_key
    }

    sent: List[str] = []
    failed: List[Dict[str, Any]] = []

    # Process each recipient individually to maintain pipeline reliability goals
    for to_addr in to_addrs:
        payload = {
            "sender": {"email": from_addr, "name": "MarketPulse India"},
            "to": [{"email": to_addr}],
            "subject": subject,
            "htmlContent": html_body  # Changed from textContent to htmlContent for your briefing layout
        }

        try:
            # Short timeout to keep the pipeline moving if a gateway drops
            response = requests.post(url, json=payload, headers=headers, timeout=10.0)
            
            if response.status_code in [200, 201, 202]:
                sent.append(to_addr)
            else:
                failed.append({
                    "address": to_addr, 
                    "error": f"Brevo API rejected request ({response.status_code}): {response.text}"
                })
        except requests.exceptions.RequestException as exc:
            failed.append({
                "address": to_addr, 
                "error": f"HTTP post failed: {str(exc)}"
            })

    return {"sent": sent, "failed": failed, "total": len(to_addrs)}

def load_subscriber_list() -> list:
    """
    Subscriber source of truth: the Supabase `subscribers` table
    (persistence/subscriber_repo.py), per PRD Section 3 ("Supabase" for
    persistence on the free tier). Falls back to the SUBSCRIBER_LIST
    env var if Supabase isn't configured (SUPABASE_URL /
    SUPABASE_SERVICE_ROLE_KEY missing) -- this keeps local dev and CI
    smoke tests working without provisioning a database, while
    production runs read from the real table.
    """
    try:
        from marketpulse.persistence.subscriber_repo import list_active_subscriber_emails

        emails = list_active_subscriber_emails()
        if emails:
            return emails
    except Exception:
        pass  # Supabase not configured / unreachable -- fall through to env var

    raw = os.environ.get("SUBSCRIBER_LIST", "")
    if raw:
        return [addr.strip() for addr in raw.split(",") if addr.strip()]
    return []
