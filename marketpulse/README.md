# MarketPulse India — MVP Implementation

Implementation of **PRD v1.6** ("Critical Path De-Risk, SEBI Token
Hardening & Override Extension"), extended with a public signup/sign-in
web app, an authenticated in-browser dashboard, and multi-channel
delivery (Email / WhatsApp / Telegram). Every module below is traceable
to a specific FR in the PRD via its docstring.

## Layout

```
marketpulse/
├── models/schemas.py            FR-01.1, FR-01.2, FR-02.2/2.3/2.5/2.6 data models,
│                                 plus DeliveryChannel / Subscriber / Session for auth
├── constants/
│   ├── paragraph4_tokens.py     FR-02.5 deterministic sentinel-token resolution
│   ├── jargon_registry.py       FR-02.4.1 jargon term registry (Appendix A glossary)
│   └── sebi_entity_rules.py     FR-02.4.2 entity blacklist + conversion matrix
├── ai_engine/
│   ├── llm_client.py            FR-02.2 Gemini 1.5 Flash sentiment/sector analysis
│   ├── jargon_enforcer.py       FR-02.4.1 Layer 2 deterministic jargon injection
│   ├── entity_scanner.py        FR-02.4.2 Layer 2 deterministic entity scrub + suppression
│   └── bias_engine.py           FR-02.3 aggregation, FR-02.5 reconciliation, FR-02.6 override
├── pipeline/
│   ├── ingestion.py             FR-01.2 RSS ingestion & event normalization
│   ├── market_data.py           FR-01.1 GIFT Nifty (3-tier fallback) + instrument snapshots
│   └── orchestrator.py          Ties 06:00→07:00 IST stages together
├── email_system/
│   ├── render.py                FR-03.1 HTML email template assembly
│   ├── sender.py                Batched SMTP dispatch to the Email channel
│   └── transactional.py         One-off transactional emails (verification link, etc.)
├── delivery/                     Multi-channel fan-out layer
│   ├── text_render.py            Plain-text + Telegram MarkdownV2 versions of the briefing
│   ├── whatsapp_sender.py        Twilio WhatsApp Business API sender
│   ├── telegram_sender.py        Telegram Bot API sender + /start webhook handler
│   └── dispatcher.py              Fans out one day's briefing to Email + WhatsApp + Telegram
├── webapp/
│   └── index.html                 Single-file app: landing (sign-up/sign-in) + dashboard
├── api/                            Backend for the web app
│   ├── handlers.py                 Signup/verify/login/logout/me/briefing/telegram-link/etc.
│   └── app.py                      Flask routes wiring handlers.py to HTTP
├── persistence/                   Supabase persistence layer
│   ├── schema.sql                  DDL: subscribers, sessions, email_verifications,
│   │                                telegram_links, market_closes, pipeline_runs, send_log
│   ├── supabase_client.py          Thin PostgREST HTTP wrapper (no supabase-py dep)
│   ├── subscriber_repo.py          Subscriber CRUD, password auth, email verification,
│   │                                Telegram linking
│   ├── session_repo.py             Session token issuance/lookup/revocation
│   ├── market_close_repo.py        Previous-day Nifty close storage + lookup
│   └── run_log_repo.py             PipelineRunRecord + per-channel send-result audit,
│                                    plus cached briefing HTML/text for the dashboard
├── scheduler/
│   ├── run_daily_briefing.py       GitHub Actions cron entry point (06:00→07:00 IST)
│   └── record_daily_close.py       EOD job: persists today's official Nifty close
├── utils/
│   ├── timeutils.py                IST checkpoint helpers (06:00/06:45/06:50/07:00)
│   └── qa_logging.py               Structured stdout audit log of every run
├── tests/                          106 unit tests covering all deterministic logic,
│                                    persistence repos, auth/session flows, API handlers,
│                                    and chat-channel rendering
├── .env.example                    All required environment variables, documented
└── .github/workflows/daily_briefing.yml   Free-tier cron scheduling (2 jobs)
```

## Authentication & the in-browser dashboard

**The landing page is sign-up / sign-in, not a bare mailing-list form.**
`webapp/index.html` opens on an auth card with two tabs: Sign up (email
or mobile number + password + delivery channels) and Sign in (email or
mobile number + password). After a successful sign-in, the same
single-page app swaps client-side to a dashboard view that renders
**today's actual briefing inline** — this is the "view MarketPulse on
the website after login" requirement.

### How it works

1. **Sign up** (`POST /api/signup`) requires a password and at least one
   of email/mobile number. If an email is given, a verification link is
   sent and the account stays `pending_verification` until clicked — a
   mobile-only signup activates immediately (there's no email to
   verify). Either way, a password is always set, so signing in is
   possible as soon as the account is active.
2. **Sign in** (`POST /api/login`) accepts either an email or a mobile
   number plus the password, looked up by whichever shape the input has
   (`@` → email, else → mobile). On success it returns an opaque
   session token (not a JWT — see `persistence/session_repo.py`'s
   docstring for why) that the web app stores and sends back as a
   `Authorization: Bearer <token>` header on every subsequent request.
3. **The dashboard** (`GET /api/briefing/latest`) reads the most
   recently cached briefing render (`pipeline_runs.briefing_html`,
   written by `scheduler/run_daily_briefing.py` once the day's pipeline
   completes) and displays it inline in a sandboxed `<iframe>` — no
   pipeline re-run, no re-render, just a read of the cached row.
4. **Session restore on reload**: the web app keeps the token in
   `localStorage` and calls `GET /api/me` on load to silently restore
   the signed-in state without re-prompting for credentials, until the
   token is revoked (logout) or expires (30 days).
5. **Delivery channel management** moved into the dashboard too
   (`POST /api/channels`, `POST /api/telegram/link`) — both now require
   an authenticated session rather than a bare email string in the
   request body, closing the gap where anyone who knew (or guessed) a
   subscriber's email could previously change their delivery
   preferences or request a Telegram link on their behalf.

### Security notes

- Passwords are hashed with `werkzeug.security` (scrypt) before ever
  reaching Supabase — `password_hash` is never returned in any API
  response (`Subscriber.to_public_dict()` is the single serialization
  path every handler uses, specifically so a future field added to the
  dataclass can't accidentally leak into a JSON response).
- Login failure messages are identical whether the account doesn't
  exist or the password is wrong, so a login attempt can't be used to
  enumerate registered emails/numbers.
- Sessions are DB-backed (`sessions` table), not stateless tokens, so
  logout and "sign out everywhere" (`revoke_all_sessions_for_subscriber`)
  are a single `UPDATE` rather than needing a token blocklist.
- Telegram linking still requires a *verified* email anchor even for an
  authenticated session — a mobile-only account can sign in and view the
  dashboard, but can't link Telegram until it also adds and verifies an
  email, since that binding was deliberately built to never trust an
  unverified identity claim.

## Multi-channel delivery

`scheduler/run_daily_briefing.py` calls
`delivery.dispatcher.dispatch_all_channels()` once the pipeline output is
ready, fanning out to every active subscriber across Email (batched
SMTP), WhatsApp (Twilio), and Telegram (Bot API). All three renderers
consume the same `pipeline_output` dict, so the channels never diverge
in substance — only formatting. The same render is also what gets
cached onto `pipeline_runs.briefing_html` / `briefing_text` for the
website dashboard to display, so a signed-in user sees exactly what was
sent to their inbox/chat that morning.

WhatsApp's 24-hour messaging-session rule (Meta policy) means production
sending should use an approved Message Template — see
`delivery/whatsapp_sender.py`'s `WHATSAPP_TEMPLATE_NOTE`.

## Persistence layer (Supabase)

| Table | Purpose |
|---|---|
| `subscribers` | Identity, password hash, channel preferences (`channels text[]`, `telegram_chat_id`, `whatsapp_number`, `mobile_number`) |
| `sessions` | Opaque session tokens issued at login, backing the dashboard |
| `email_verifications` | One-time tokens for the signup confirmation flow |
| `telegram_links` | Short-lived codes for the `/start` deep-link binding flow |
| `market_closes` | Yesterday's official Nifty 50 close (baseline for GIFT Nifty %) |
| `pipeline_runs` | One audit row per daily run, plus cached `briefing_html`/`briefing_text` |
| `send_log` | Per-recipient, per-channel delivery outcome |

See `persistence/schema.sql` for full DDL and RLS posture (default-deny;
the backend uses the service-role key server-side — the browser never
talks to Supabase directly, only to `api/app.py`'s endpoints, and
`password_hash` is never reachable from a public key even if one were
ever exposed).

### Setting up Supabase

1. Create a free-tier Supabase project.
2. Run `persistence/schema.sql` in the Supabase SQL editor (or
   `supabase db push`).
3. Set `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` (service role, never
   anon) as secrets / in `.env` — see `.env.example`.

## Key design decisions traced to the PRD

- **Zero LLM calls in the critical 06:45→06:50 window** (FR-02.5):
  Paragraph 4 is never generated live — resolved from one of three
  sentinel tokens via pure string templates in `constants/paragraph4_tokens.py`.
- **Two-layer jargon/entity safety nets** (FR-02.4.1 / FR-02.4.2): LLM
  self-compliance (Layer 1) plus a deterministic regex pass (Layer 2),
  with run suppression if entity leakage is severe.
- **Domestic override** (FR-02.6): a high-intensity `INDIA_DOMESTIC`
  event is weighted 70/30 against the rest of the day's global news.
- **Multi-channel content parity**: every channel — including the
  website dashboard — renders from the same pipeline output, so nothing
  ever diverges in substance, only formatting.
- **Verified-identity-first signup, session-gated everything else**:
  WhatsApp/Telegram and channel management are additive to a real
  account, never reachable by guessing an email string in a request
  body.
- **Infra stays inside the $16–26/mo budget** (Section 3): free RSS
  feeds, Gemini 1.5 Flash free tier, GitHub Actions free-tier cron, SMTP
  via a free-tier provider, Supabase free tier, Telegram's free Bot API,
  and Twilio's free WhatsApp Sandbox for development.

## Running

```bash
pip install -r requirements.txt
python -m unittest discover -s marketpulse/tests

# Local dev: copy .env.example to .env and fill in real values, then:
export $(grep -v '^#' .env | xargs)

# Run the web app + API locally:
python -m marketpulse.api.app   # serves webapp/index.html + /api/* on :8000

# Manual full-pipeline run (skips sleep-until-checkpoint waits):
python -m marketpulse.scheduler.run_daily_briefing --prev-close 24838.20 --skip-wait

# End-of-day close recording (normally on its own cron):
python -m marketpulse.scheduler.record_daily_close
```

## What's stubbed vs. production-ready

- **Production-ready, fully tested (106 tests)**: jargon enforcement,
  entity scrubbing, bias reconciliation, domestic override, sector
  aggregation, sentinel token resolution, HTML/plain-text/Telegram
  rendering, the full Supabase persistence layer including password
  hashing and session management, every API handler (signup, verify,
  login, logout, me, briefing/latest, telegram-link, channels,
  unsubscribe) exercised end-to-end through Flask's test client, and the
  audit-flattening logic in the dispatcher.
- **Stubbed network calls** (interfaces match the PRD's specified
  sources/providers exactly, need live credentials to fully exercise):
  RSS ingestion, GIFT Nifty 3-tier fallback, Yahoo Finance snapshots,
  Gemini API, SMTP send, Twilio WhatsApp send, Telegram Bot API send,
  and the live PostgREST HTTP round-trip itself.
