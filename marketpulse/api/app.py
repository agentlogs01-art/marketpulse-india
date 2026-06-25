"""
api/app.py

Thin Flask wiring around api/handlers.py. Flask is used here because
it's the lowest-friction way to expose a handful of JSON endpoints on
Railway (PRD Section 3 infra: Railway.app) without adding a heavier
framework -- this app serves webapp/index.html as a static file plus
the signup/sign-in/dashboard JSON API.

Session tokens travel as a Bearer token in the Authorization header
(set by the web app's JS after a successful login) -- not a cookie, so
there's no CSRF surface to manage and the same endpoints work cleanly
from a non-browser client later if needed. Falls back to a JSON body
`session_token` field too, purely to keep curl/manual testing simple.

Run locally:
    pip install flask
    FLASK_APP=marketpulse.api.app flask run --port 8000

Deploy: Railway can run this directly via
    gunicorn marketpulse.api.app:app
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, request, send_from_directory

from marketpulse.api.handlers import (
    AuthError,
    ValidationError,
    get_current_subscriber,
    get_latest_briefing,
    login,
    logout,
    request_telegram_link,
    signup,
    unsubscribe,
    update_channels,
    verify_email,
)

app = Flask(__name__)

_WEBAPP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "webapp")


def _json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


@app.errorhandler(ValidationError)
def handle_validation_error(exc: ValidationError):
    return _json_error(str(exc), 400)


@app.errorhandler(AuthError)
def handle_auth_error(exc: AuthError):
    return _json_error(str(exc), 401)


def _session_token_from_request() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):].strip()
    body = request.get_json(force=True, silent=True) or {}
    return body.get("session_token", "")


# ---------------------------------------------------------------------------
# Static web app
# ---------------------------------------------------------------------------

@app.route("/")
def serve_index():
    """
    The landing page is sign-up / sign-in (webapp/index.html). Once
    signed in, the same single-page app swaps to the dashboard view
    client-side using the session token from POST /api/login -- there is
    no separate server route for the dashboard, so a page refresh after
    login re-resolves the session via GET /api/me (see index.html).
    """
    return send_from_directory(_WEBAPP_DIR, "index.html")


@app.route("/verify")
def serve_verify_page():
    """
    The verification link emailed to the person points here with
    ?token=... in the query string; index.html's JS reads it and calls
    POST /api/verify.
    """
    return send_from_directory(_WEBAPP_DIR, "index.html")


# ---------------------------------------------------------------------------
# JSON API -- signup / verification
# ---------------------------------------------------------------------------

@app.route("/api/signup", methods=["POST"])
def api_signup():
    body = request.get_json(force=True, silent=True) or {}
    result = signup(
        password=body.get("password", ""),
        email=body.get("email"),
        mobile_number=body.get("mobile_number"),
        channels=body.get("channels"),
        whatsapp_number=body.get("whatsapp_number"),
    )
    return jsonify(result)


@app.route("/api/verify", methods=["POST"])
def api_verify():
    body = request.get_json(force=True, silent=True) or {}
    token = body.get("token", "") or request.args.get("token", "")
    result = verify_email(token)
    return jsonify(result)


# ---------------------------------------------------------------------------
# JSON API -- sign-in / sign-out / session
# ---------------------------------------------------------------------------

@app.route("/api/login", methods=["POST"])
def api_login():
    body = request.get_json(force=True, silent=True) or {}
    result = login(login_id=body.get("login_id", ""), password=body.get("password", ""))
    return jsonify(result)


@app.route("/api/logout", methods=["POST"])
def api_logout():
    result = logout(_session_token_from_request())
    return jsonify(result)


@app.route("/api/me", methods=["GET"])
def api_me():
    result = get_current_subscriber(_session_token_from_request())
    return jsonify(result)


# ---------------------------------------------------------------------------
# JSON API -- authenticated dashboard (view MarketPulse after sign-in)
# ---------------------------------------------------------------------------

@app.route("/api/briefing/latest", methods=["GET"])
def api_briefing_latest():
    result = get_latest_briefing(_session_token_from_request())
    return jsonify(result)


# ---------------------------------------------------------------------------
# JSON API -- channel management / Telegram linking / unsubscribe
# ---------------------------------------------------------------------------

@app.route("/api/telegram/link", methods=["POST"])
def api_telegram_link():
    result = request_telegram_link(_session_token_from_request())
    return jsonify(result)


@app.route("/api/unsubscribe", methods=["POST"])
def api_unsubscribe():
    body = request.get_json(force=True, silent=True) or {}
    result = unsubscribe(email=body.get("email", ""))
    return jsonify(result)


@app.route("/api/channels", methods=["POST"])
def api_update_channels():
    body = request.get_json(force=True, silent=True) or {}
    result = update_channels(_session_token_from_request(), channels=body.get("channels", []))
    return jsonify(result)


# ---------------------------------------------------------------------------
# Telegram webhook
# ---------------------------------------------------------------------------

@app.route("/api/telegram/webhook", methods=["POST"])
def telegram_webhook():
    """
    Telegram POSTs every incoming message/update here once setWebhook has
    been configured (see delivery/telegram_sender.py's module docstring).
    Always returns 200 quickly -- Telegram retries aggressively on
    non-200 responses, and a /start for an invalid/expired link_code is
    an expected, not exceptional, case.
    """
    from marketpulse.delivery.telegram_sender import handle_start_command
    from marketpulse.email_system.transactional import send_telegram_linked_confirmation

    update = request.get_json(force=True, silent=True) or {}
    subscriber_dict = handle_start_command(update)

    if subscriber_dict and subscriber_dict.get("email"):
        try:
            send_telegram_linked_confirmation(subscriber_dict["email"])
        except Exception:
            pass  # confirmation email is a nice-to-have, never block the webhook ack

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
