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

from flask import Flask, jsonify, request, send_from_directory, Response
from werkzeug.exceptions import HTTPException
from dotenv import load_dotenv
import os

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(_REPO_ROOT, ".env"))
load_dotenv(os.path.join(_REPO_ROOT, "marketpulse", ".env"))

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
    update_profile,
    verify_email,
)
from marketpulse.api import investor_handlers

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


@app.errorhandler(Exception)
def handle_unexpected_error(exc: Exception):
    """Keep API clients on JSON even when login/signup hits a server fault."""
    if isinstance(exc, HTTPException):
        return exc
    from marketpulse.persistence.supabase_client import SupabaseConfigError, SupabaseRequestError

    app.logger.exception("Unhandled API error: %s", exc)
    if isinstance(exc, SupabaseConfigError):
        return _json_error(
            "Database is not configured. Copy marketpulse/.env.example to marketpulse/.env "
            "and set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, then restart the server.",
            503,
        )
    if isinstance(exc, SupabaseRequestError):
        return _json_error("Could not reach the account database. Try again shortly.", 503)
    return _json_error("Something went wrong. Please try again.", 500)


def _session_token_from_request() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):].strip()
    if request.form.get("session_token"):
        return request.form.get("session_token", "")
    body = request.get_json(force=True, silent=True) or {}
    return body.get("session_token", "")


# ---------------------------------------------------------------------------
# Static web app
# ---------------------------------------------------------------------------

@app.route("/favicon.ico")
def favicon():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="8" fill="#0B0E14"/>'
        '<path d="M8 22 L16 8 L24 22" fill="none" stroke="#00D084" stroke-width="2.5"/>'
        "</svg>"
    )
    return Response(svg, mimetype="image/svg+xml")


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
        first_name=body.get("first_name"),
        last_name=body.get("last_name"),
    )
    # If the dictionary payload indicates an error status, assign a 400 status code
    if isinstance(result, dict) and result.get("status") == "error":
        return jsonify(result), 400
    else:
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


@app.route("/api/profile", methods=["POST"])
def api_update_profile():
    body = request.get_json(force=True, silent=True) or {}
    result = update_profile(
        _session_token_from_request(),
        first_name=body.get("first_name"),
        last_name=body.get("last_name"),
        email=body.get("email"),
        whatsapp_number=body.get("whatsapp_number"),
        telegram_chat_id=body.get("telegram_chat_id"),
    )
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
# JSON API v1 — long-term investor (additive; legacy /api/* unchanged)
# ---------------------------------------------------------------------------

@app.route("/api/v1/portfolio/upload", methods=["POST"])
def api_v1_portfolio_upload():
    upload = request.files.get("file")
    raw = upload.read() if upload else b""
    filename = upload.filename if upload else ""
    broker_token = request.form.get("broker_token") or ""
    if not broker_token:
        body = request.get_json(force=True, silent=True) or {}
        broker_token = body.get("broker_token") or ""
        if not raw:
            raw = (body.get("csv") or body.get("text") or "").encode("utf-8")
            filename = filename or body.get("filename") or "upload.csv"
    result = investor_handlers.upload_portfolio(
        _session_token_from_request(),
        raw=raw,
        filename=filename,
        broker_token=broker_token,
    )
    return jsonify(result)


@app.route("/api/v1/portfolio/analysis", methods=["GET"])
def api_v1_portfolio_analysis():
    return jsonify(investor_handlers.get_portfolio_analysis(_session_token_from_request()))


@app.route("/api/v1/stocks/search", methods=["GET"])
def api_v1_stocks_search():
    q = request.args.get("q", "")
    universe = (request.args.get("universe") or request.args.get("asset") or "").lower()
    index_only = request.args.get("index_only", "").lower() in {"1", "true", "yes"}
    if universe in {"funds", "mf", "mutual_fund", "mutual-funds"} or index_only:
        return jsonify(
            investor_handlers.search_mutual_funds(
                _session_token_from_request(),
                q,
                request.args.get("category", ""),
                index_only,
            )
        )
    return jsonify(investor_handlers.search_stock_symbols(_session_token_from_request(), q))


@app.route("/api/v1/stocks/<symbol>", methods=["GET"])
def api_v1_stock_detail(symbol):
    return jsonify(investor_handlers.get_stock_detail(_session_token_from_request(), symbol))


@app.route("/api/v1/investor/valuation-zone", methods=["GET"])
def api_v1_valuation_zone():
    return jsonify(investor_handlers.get_valuation_zone(_session_token_from_request()))


@app.route("/api/v1/fixed-income/secured", methods=["GET"])
def api_v1_fixed_income_secured():
    return jsonify(investor_handlers.get_secured_fixed_income(_session_token_from_request()))


@app.route("/api/v1/investor/tickers", methods=["GET"])
def api_v1_investor_tickers_get():
    return jsonify(investor_handlers.get_ticker_watchlist(_session_token_from_request()))


@app.route("/api/v1/investor/tickers", methods=["POST"])
def api_v1_investor_tickers_post():
    body = request.get_json(force=True, silent=True) or {}
    return jsonify(
        investor_handlers.set_ticker_favorite(
            _session_token_from_request(),
            body.get("symbol") or "",
            bool(body.get("is_favorite")),
        )
    )


@app.route("/api/v1/investor/notifications", methods=["GET"])
def api_v1_investor_notifications():
    return jsonify(investor_handlers.get_investor_notifications(_session_token_from_request()))


@app.route("/api/v1/mutual-funds", methods=["GET"])
def api_v1_mutual_funds():
    q = (request.args.get("q") or "").strip()
    index_only = request.args.get("index_only", "").lower() in {"1", "true", "yes"}
    if q or index_only:
        return jsonify(
            investor_handlers.search_mutual_funds(
                _session_token_from_request(),
                q,
                request.args.get("category", ""),
                index_only,
            )
        )
    return jsonify(investor_handlers.list_mutual_funds(_session_token_from_request()))


@app.route("/api/v1/investor/funds/search", methods=["GET"])
def api_v1_investor_funds_search():
    """Dedicated search path so it cannot clash with /mutual-funds/<code>."""
    return jsonify(
        investor_handlers.search_mutual_funds(
            _session_token_from_request(),
            request.args.get("q", ""),
            request.args.get("category", ""),
            request.args.get("index_only", "").lower() in {"1", "true", "yes"},
        )
    )


@app.route("/api/v1/mutual-funds/search", methods=["GET"])
def api_v1_mutual_funds_search():
    return api_v1_investor_funds_search()


@app.route("/api/v1/mutual-funds/<code>", methods=["GET"])
def api_v1_mutual_fund_detail(code):
    if code.lower() == "search":
        return api_v1_investor_funds_search()
    return jsonify(investor_handlers.get_mutual_fund_detail(_session_token_from_request(), code))


# ---------------------------------------------------------------------------
# Telegram webhook
# ---------------------------------------------------------------------------

@app.route("/api/telegram/webhook", methods=["POST"])
def telegram_webhook():
    """
    Telegram POSTs every incoming message/update here once setWebhook has
    been configured with secret_token (see telegram_sender.register_webhook).
    Always returns 200 for authorized, well-formed updates -- Telegram
    retries aggressively on non-200, and an invalid/expired link_code is
    an expected case. Unauthorized callers get 401.
    """
    from marketpulse.delivery.telegram_sender import (
        TELEGRAM_WEBHOOK_HEADER,
        handle_start_command,
        telegram_webhook_authorized,
    )
    from marketpulse.email_system.transactional import send_telegram_linked_confirmation

    if not telegram_webhook_authorized(request.headers.get(TELEGRAM_WEBHOOK_HEADER)):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    update = request.get_json(force=True, silent=True) or {}
    subscriber_dict = handle_start_command(update)

    if subscriber_dict and subscriber_dict.get("email"):
        try:
            send_telegram_linked_confirmation(subscriber_dict["email"])
        except Exception:
            pass  # confirmation email is a nice-to-have, never block the webhook ack

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        threaded=True,
        debug=True,
        use_reloader=True,
    )
