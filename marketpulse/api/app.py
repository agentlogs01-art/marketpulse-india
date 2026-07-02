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

import io
import qrcode
from flask import jsonify, send_file, request

import os

from flask import Flask, jsonify, request, send_from_directory

from marketpulse.api.handlers import (
    AuthError,
    ValidationError,
    change_password,
    get_current_subscriber,
    get_latest_briefing,
    login,
    login_mfa,
    logout,
    mfa_disable,
    mfa_enroll_confirm,
    mfa_enroll_start,
    mfa_regenerate_backup_codes,
    request_password_reset,
    request_telegram_link,
    reset_password,
    signup,
    unsubscribe,
    update_channels,
    update_theme_preference,
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

@app.route("/reset-password")
def serve_reset_password_page():
    """
    The password-reset link emailed by request_password_reset() points
    here with ?token=... in the query string; index.html's JS detects
    this the same way it detects an email-verification token and shows
    the "choose a new password" form instead of the sign-up/sign-in tabs.
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

@app.route("/api/login/mfa", methods=["POST"])
def api_login_mfa():
    body = request.get_json(force=True, silent=True) or {}
    result = login_mfa(challenge_token=body.get("challenge_token", ""), code=body.get("code", ""))
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
# JSON API -- password change (authenticated) & reset (unauthenticated)
# ---------------------------------------------------------------------------
 
@app.route("/api/password/change", methods=["POST"])
def api_change_password():
    body = request.get_json(force=True, silent=True) or {}
    result = change_password(
        _session_token_from_request(),
        current_password=body.get("current_password", ""),
        new_password=body.get("new_password", ""),
    )
    return jsonify(result)
 
 
@app.route("/api/password/forgot", methods=["POST"])
def api_request_password_reset():
    body = request.get_json(force=True, silent=True) or {}
    result = request_password_reset(login_id=body.get("login_id", ""))
    return jsonify(result)
 
 
@app.route("/api/password/reset", methods=["POST"])
def api_reset_password():
    body = request.get_json(force=True, silent=True) or {}
    token = body.get("token", "") or request.args.get("token", "")
    result = reset_password(token=token, new_password=body.get("new_password", ""))
    return jsonify(result)
 
 
# ---------------------------------------------------------------------------
# JSON API -- multi-factor authentication (Profile page)
# ---------------------------------------------------------------------------
 
@app.route("/api/mfa/enroll/start", methods=["POST"])
def api_mfa_enroll_start():
    result = mfa_enroll_start(_session_token_from_request())
    return jsonify(result)
 
@app.route("/api/mfa/enroll/confirm", methods=["POST"])
def api_mfa_enroll_confirm():
    body = request.get_json(force=True, silent=True) or {}
    result = mfa_enroll_confirm(_session_token_from_request(), code=body.get("code", ""))
    return jsonify(result)
 
 
@app.route("/api/mfa/disable", methods=["POST"])
def api_mfa_disable():
    body = request.get_json(force=True, silent=True) or {}
    result = mfa_disable(_session_token_from_request(), password=body.get("password", ""))
    return jsonify(result)
 
 
@app.route("/api/mfa/backup-codes/regenerate", methods=["POST"])
def api_mfa_regenerate_backup_codes():
    result = mfa_regenerate_backup_codes(_session_token_from_request())
    return jsonify(result)
 
 
# ---------------------------------------------------------------------------
# JSON API -- theme preference
# ---------------------------------------------------------------------------
 
@app.route("/api/theme", methods=["POST"])
def api_update_theme():
    body = request.get_json(force=True, silent=True) or {}
    result = update_theme_preference(_session_token_from_request(), theme=body.get("theme", ""))
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
