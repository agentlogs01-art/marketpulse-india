"""
email_system/transactional.py

One-off transactional emails (signup verification link) -- distinct from
email_system/sender.py's send_email(), which is built for the single
daily batched briefing send to many recipients in one SMTP session. This
module sends ONE email to ONE address per call, which is the right shape
for "click to verify your email" / "your Telegram is now linked" style
notifications.

Reuses the same SMTP_* environment variables as email_system/sender.py
(same SMTP account is fine for both transactional and briefing mail at
MVP volume) -- no new infra cost.
"""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText


class TransactionalEmailError(Exception):
    pass


def send_verification_email(to_email: str, verify_url: str) -> None:
    subject = "Confirm your MarketPulse India subscription"
    body = (
        "Welcome to MarketPulse India!\n\n"
        "Click the link below to confirm your email address and start "
        "receiving your daily pre-market briefing before NSE open:\n\n"
        f"{verify_url}\n\n"
        "This link expires in 24 hours. If you didn't request this, you can "
        "safely ignore this email -- no account will be created.\n\n"
        "-- MarketPulse India"
    )
    _send_plain_text(to_email, subject, body)


def send_telegram_linked_confirmation(to_email: str) -> None:
    subject = "Telegram connected to MarketPulse India"
    body = (
        "Your Telegram account is now connected. You'll start receiving "
        "your daily pre-market briefing there from the next scheduled run.\n\n"
        "-- MarketPulse India"
    )
    _send_plain_text(to_email, subject, body)


def _send_plain_text(to_email: str, subject: str, body: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("EMAIL_FROM_ADDRESS", smtp_user or "noreply@marketpulseindia.app")

    if not all([smtp_host, smtp_user, smtp_password]):
        raise TransactionalEmailError("SMTP credentials not fully configured in environment")

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(from_addr, [to_email], msg.as_string())
