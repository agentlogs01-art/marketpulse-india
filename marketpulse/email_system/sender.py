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
import smtplib
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
    Send the briefing to a list of subscriber addresses. Returns a result
    dict with per-recipient success/failure so a single bad address
    doesn't silently drop the whole batch (FR pipeline reliability goal:
    07:00 IST send should reach as many subscribers as possible even if
    one address bounces at SMTP-connect time).
    """
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("EMAIL_FROM_ADDRESS", smtp_user or "noreply@marketpulseindia.app")

    if not all([smtp_host, smtp_user, smtp_password]):
        raise EmailSendError("SMTP credentials not fully configured in environment")

    sent: list = []
    failed: list = []

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)

        for to_addr in to_addrs:
            try:
                msg = _build_message(subject, html_body, from_addr, to_addr)
                server.sendmail(from_addr, [to_addr], msg.as_string())
                sent.append(to_addr)
            except Exception as exc:
                failed.append({"address": to_addr, "error": str(exc)})

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
