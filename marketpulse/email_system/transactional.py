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
import requests
import smtplib
from email.mime.text import MIMEText


class TransactionalEmailError(Exception):
    pass

def send_mfa_enabled_notification(to_email: str) -> None:
    subject = "Two-factor authentication enabled on your MarketPulse India account"
    body = (
        "Two-factor authentication was just turned on for your account. "
        "From now on, signing in will require both your password and a code "
        "from your authenticator app.\n\n"
        "If you didn't make this change, please contact support immediately.\n\n"
        "-- MarketPulse India"
    )
    _send_plain_text(to_email, subject, body)
 
 
def send_mfa_disabled_notification(to_email: str) -> None:
    subject = "Two-factor authentication disabled on your MarketPulse India account"
    body = (
        "Two-factor authentication was just turned off for your account. "
        "Signing in now only requires your password.\n\n"
        "If you didn't make this change, please contact support immediately "
        "and change your password.\n\n"
        "-- MarketPulse India"
    )
    _send_plain_text(to_email, subject, body)

def _send_plain_text(to_email, subject, body):
    # For the Web API, Brevo requires your master API Key (usually starts with xkeysib-)
    # Store this in your Railway Variables as BREVO_API_KEY
    api_key = os.environ.get("BREVO_API_KEY") or os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("EMAIL_FROM_ADDRESS", "agentlogs01@gmail.com")

    if not api_key:
        print("[-] Brevo API Key missing. Skipping email signup dispatch.")
        return False

    url = "https://api.brevo.com/v3/smtp/email"
    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": api_key
    }
    
    payload = {
        "sender": {"email": from_addr, "name": "MarketPulse India"},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": body
    }

    try:
        print(f"[~] Attempting outbound HTTP API email dispatch to {to_email}...")
        response = requests.post(url, json=payload, headers=headers, timeout=5.0)
        
        if response.status_code in [200, 201, 202]:
            print(f"[✓] Transactional API call successful! Message ID: {response.json().get('messageId')}")
            return True
        else:
            print(f"[-] Brevo API rejected payload ({response.status_code}): {response.text}")
            return False

    except requests.exceptions.RequestException as exc:
        print(f"[-] HTTP API connection failed: {exc}")
        return False    


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

