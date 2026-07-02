# MarketPulse India — Core Application Module

**Version**: 1.6.0 | **Language**: Python (82.4%) | Built against PRD v1.6 (Critical Path De-Risk, SEBI Token Hardening & Override Extension)

---

## 📌 Overview

The `marketpulse/` module is the heart of the MarketPulse India platform — an **AI-powered pre-market intelligence system** delivering daily market briefings to Indian equity traders. It ingests curated news sources, reconciles LLM-driven sentiment with market snapshots, and delivers a concise briefing across email, Telegram and WhatsApp to subscribed users.

**Core Design Principle**: Graceful degradation at every stage. A single source failure or LLM timeout never blocks the morning send — the pipeline falls back to neutral analysis or suppresses the run as appropriate.

---

## 🏗️ Module Architecture

```
marketpulse/
│
├── api/                     # REST API + Web Dashboard (Flask)
│   ├── app.py               # Flask wiring: static webapp, JSON endpoints
│   └── handlers.py          # Auth, MFA, session, subscription logic
│
├── pipeline/                # Daily briefing orchestration (06:00 – 07:00 IST)
│   ├── orchestrator.py      # Top-level run_full_pipeline() + AI analysis stage
│   ├── ingestion.py         # RSS feed fetch + event normalization (FR-01.2)
│   └── market_data.py       # GIFT Nifty + instrument snapshots (FR-01.1)
│
├── ai_engine/               # Sentiment analysis & bias reconciliation
│   ├── llm_client.py        # LLM calls for event analysis (FR-02.2)
│   ├── bias_engine.py       # Sector scoring + bias reconciliation (FR-02.3/02.5)
│   ├── jargon_enforcer.py   # Beginner-friendly text enforcement
│   └── entity_scanner.py    # Entity genericization (FR-02.4.2)
│
├── delivery/                # Multi-channel dispatch
│   ├── dispatcher.py        # Orchestration: email + Telegram + WhatsApp
│   ├── text_render.py       # Plain-text briefing render
│   ├── telegram_sender.py   # Telegram API integration
│   └── whatsapp_sender.py   # WhatsApp (Twilio) integration
│
├── email_system/            # Email rendering & transactional mail
│   ├── render.py            # HTML email template rendering
│   ├── sender.py            # SMTP delivery (SendGrid / Resend)
│   └── transactional.py     # Verification, password reset, MFA emails
│
├── models/                  # Data schemas & domain objects
│   ├── __init__.py
│   └── schemas.py           # NewsEvent, EventAnalysis, Subscriber, Session, etc.
│
├── persistence/             # Database layer (Supabase PostgreSQL)
│   ├── supabase_client.py   # Authenticated Supabase client
│   ├── subscriber_repo.py   # Subscriber CRUD + auth (email, MFA, password)
│   ├── session_repo.py      # Session token management
│   ├── market_close_repo.py # Official Nifty 50 daily closes
│   ├── run_log_repo.py      # Pipeline audit logs
│   ├── mfa_repo.py          # MFA secret / backup codes (TOTP RFC 6238)
│   └── schema.sql           # Database DDL: tables, constraints, indexes
│
├── scheduler/               # Background cron jobs (GitHub Actions)
│   ├── run_daily_briefing.py  # Entry point: full pipeline + dispatch (07:00 IST)
│   └── record_daily_close.py  # Fetch & record Nifty 50 official close (16:00 IST)
│
├── constants/               # Lookup tables & constants
│   ├── paragraph4_tokens.py # Bias description templates
│   └── ...
│
├── utils/                   # Helpers: time, logging, etc.
│   ├── qa_logging.py        # QA audit trail (jargon/entity violations)
│   └── ...
│
├── webapp/                  # Frontend (HTML + JavaScript, 17.6%)
│   └── index.html           # Single-page app: signup, login, dashboard
│
├── docs/                    # Documentation & deployment guides
│   └── ...
│
└── tests/                   # Unit & integration tests
    └── ...
```

---

## 🔄 Daily Pipeline Flow (06:00 – 07:00 IST)

The briefing generation follows a strict IST timeline, orchestrated by GitHub Actions and internal time checkpoints in the scheduler scripts.

### **Stage 1: Pre-Render (06:00 IST)**
- Static HTML template shell rendered; used as fallback if stage 2 fails

### **Stage 2: Snapshot (06:45 IST)** — `pipeline/market_data.py`
- Fetch **GIFT Nifty** (^NSEI) from NSE iFC API; fall back to Yahoo Finance → Stooq
- Capture **instrument snapshots** (commodities, currency, indices) from external APIs
- Flag stale data (>6 hours old) for transparency in briefing

### **Stage 3: Ingestion** — `pipeline/ingestion.py` (any time, before assembly)
- Pull from curated RSS sources (NSE, RBI, Reuters, MarketWatch, etc.)
- Classify events by type (CENTRAL_BANK, EARNINGS, MACRO_DATA, INDIA_DOMESTIC, etc.)
- Normalize into `NewsEvent` schema; filter by 16-hour lookback window
- Resilience: single source down doesn't abort the run

### **Stage 4: AI Analysis (06:50 IST)** — `pipeline/orchestrator.py`
- For each event, call LLM to generate:
  - **Sentiment**: BULLISH | BEARISH | NEUTRAL | MIXED
  - **Affected Sectors**: one per sector (BANKING, IT, AUTO, ENERGY, FMCG)
  - **Direction & Magnitude**: POSITIVE/NEGATIVE, 1–5 impact level
  - **One-line beginner summary** (max 25 words)
- Apply deterministic enforcers:
  - **Jargon Enforcer**: inject plain-English definitions for financial terms
  - **Entity Scanner**: genericize company names (e.g., "TCS" → "major IT firm")
  - Violate safety thresholds? Suppress the run (non-fatal)

### **Stage 5: Aggregation & Reconciliation** — `ai_engine/bias_engine.py`
- **Sector Scorecard**: weighted average of sentiment magnitudes per sector
- **GIFT Nifty Bias**: reconcile LLM signals vs. actual GIFT Nifty gap
  - Gap >1% up → GAP_UP_STRONG | Gap <−1% down → GAP_DOWN_STRONG | else FLAT
- **Divergence Detection**: if signals conflict with GIFT gap (e.g., bearish events but +0.5% gap), flag for transparency
- **Domestic Override (FR-02.6)**: high-intensity INDIA_DOMESTIC events can override bias if conditions met

### **Stage 6: Render & Send (07:00 IST)** — `email_system/render.py` + `delivery/`
- Render HTML email template with sector scorecards, bias badge, top events, GIFT snapshot
- Render plain-text version for SMS/Telegram
- **Fan-out dispatch**:
  - **Email**: SendGrid / Resend API or SMTP gateway
  - **Telegram**: Direct API push or webhook callback
  - **WhatsApp**: Twilio API
- Audit log: who received, who bounced, delivery status

---

## 🔐 API & Authentication

### **REST Endpoints** — `api/app.py` + `api/handlers.py`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Serve single-page app (index.html) |
| `/api/signup` | POST | Create account (email, phone, delivery channels) |
| `/api/verify` | POST | Verify email via token |
| `/api/login` | POST | Sign in; returns session token |
| `/api/login/mfa` | POST | Complete MFA challenge |
| `/api/me` | GET | Fetch current subscriber profile |
| `/api/briefing/latest` | GET | Fetch today's briefing (cached HTML + plain text) |
| `/api/channels` | POST | Update delivery channel preferences |
| `/api/mfa/enroll/start` | POST | Begin TOTP enrollment; return QR code |
| `/api/mfa/enroll/confirm` | POST | Complete MFA setup |
| `/api/mfa/disable` | POST | Disable MFA (requires password) |
| `/api/password/forgot` | POST | Request password reset email |
| `/api/password/reset` | POST | Complete password reset |
| `/api/theme` | POST | Save light/dark theme preference |
| `/api/telegram/link` | POST | Generate Telegram link code |
| `/api/telegram/webhook` | POST | Telegram bot webhook (handle /start command) |

**Session Management**:
- Bearer token in `Authorization` header or JSON `session_token` field
- 30-day expiry (configurable)
- Revoke on logout

**Error Handling**:
- `ValidationError` (400): invalid input
- `AuthError` (401): session expired or invalid credentials

---

## 🗄️ Data Models & Persistence

### **Core Schemas** — `models/schemas.py`

- **`NewsEvent`**: Ingested news item (headline, body, type, geography, credibility score)
- **`EventAnalysis`**: LLM output (sentiment, affected sectors, bias label, beginner summary)
- **`SectorScorecard`**: Aggregated direction + impact per sector
- **`GiftNiftySnapshot`**: GIFT Nifty last traded price + % change
- **`ReconciliationResult`**: Final bias label, divergence flag, domestic override status
- **`Subscriber`**: User account (email, password hash, MFA, channels, preferences)
- **`Session`**: Auth token + expiry
- **`PipelineRunRecord`**: Audit log (jargon/entity violations, suppression reason)

### **Database Schema** — Supabase (PostgreSQL) — `persistence/schema.sql`

Designed for **Supabase FREE TIER** (MVP assumptions).

#### **Table 1: `subscribers`** — User Accounts
Primary identity table. Users authenticate via **email OR mobile_number** + password, optionally with TOTP-based MFA.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key, auto-generated |
| `email` | text | Unique, nullable (but must have email OR mobile) |
| `mobile_number` | text | Unique, E.164 format (e.g., +919876543210) |
| `password_hash` | text | Never returned in API responses |
| `status` | text | `pending_verification` \| `active` \| `paused` \| `unsubscribed` |
| `persona` | text | `beginner` (MVP: single persona only) |
| `channels` | text[] | Array of `email` \| `whatsapp` \| `telegram` |
| `telegram_chat_id` | text | Unique, linked via `/start` deep-link flow |
| `whatsapp_number` | text | Unique, delivery number (may differ from login `mobile_number`) |
| `mfa_enabled` | boolean | TOTP-based MFA active? |
| `mfa_secret` | text | Base32 TOTP secret (RFC 6238) |
| `mfa_backup_codes` | jsonb | Array of hashed one-time backup codes |
| `mfa_enrolled_at` | timestamptz | When MFA was first enabled |
| `theme_preference` | text | `light` \| `dark` |
| `created_at` | timestamptz | Account creation timestamp |
| `verified_at` | timestamptz | When email was verified |
| `last_login_at` | timestamptz | Last successful login |
| `unsubscribed_at` | timestamptz | When user unsubscribed (if applicable) |

**Constraints**:
- `has_email_or_mobile`: at least one of `email` or `mobile_number` must be present
- `channels_are_valid`: only allows 'email', 'whatsapp', 'telegram'

**Indexes**:
- `idx_subscribers_status` — for querying active subscribers
- `idx_subscribers_mobile_number` — for login lookups
- `idx_subscribers_telegram_chat_id` — for Telegram linking
- `idx_subscribers_whatsapp_number` — for WhatsApp dispatch

---

#### **Table 2: `sessions`** — Authentication Tokens
Backs the website's signed-in dashboard. Sessions expire after 30 days or can be revoked on logout.

| Column | Type | Notes |
|--------|------|-------|
| `token` | text | Primary key, random opaque string |
| `subscriber_id` | UUID | Foreign key to `subscribers` |
| `created_at` | timestamptz | Issued at login |
| `expires_at` | timestamptz | Default: +30 days |
| `revoked_at` | timestamptz | Nullable; set on logout |

**Indexes**:
- `idx_sessions_subscriber` — fast lookup by user

---

#### **Table 3: `email_verifications`** — Email Verification Tokens
One-time tokens emailed during signup. Expires after 24 hours.

| Column | Type | Notes |
|--------|------|-------|
| `token` | text | Primary key |
| `subscriber_id` | UUID | Foreign key to `subscribers` |
| `created_at` | timestamptz | Issued at signup |
| `expires_at` | timestamptz | Default: +24 hours |
| `used_at` | timestamptz | Set when verified; token becomes single-use |

**Indexes**:
- `idx_email_verifications_subscriber` — lookup by subscriber

---

#### **Table 4: `telegram_links`** — Telegram Deep-Link Tracking
Tracks pending/confirmed Telegram chat_id bindings. Users receive a `/start` link code that expires in 30 minutes.

| Column | Type | Notes |
|--------|------|-------|
| `link_code` | text | Primary key, short alphanumeric |
| `subscriber_id` | UUID | Foreign key to `subscribers` |
| `created_at` | timestamptz | Issued when user clicks "Link Telegram" |
| `expires_at` | timestamptz | Default: +30 minutes |
| `consumed_at` | timestamptz | Set when `/start` command processed |
| `chat_id` | text | Telegram chat ID captured after `/start` |

**Indexes**:
- `idx_telegram_links_subscriber` — lookup by user

---

#### **Table 5: `market_closes`** — Official Nifty 50 Closes
Persists previous-day official Nifty 50 close so the 06:45 IST snapshot stage has a baseline without an extra live call.

| Column | Type | Notes |
|--------|------|-------|
| `trade_date` | date | Primary key; day of market close |
| `nifty_close` | numeric(10, 2) | Official Nifty 50 close price |
| `source` | text | "NSE official" (default) |
| `recorded_at` | timestamptz | When recorded (typically ~16:00 IST) |

---

#### **Table 6: `pipeline_runs`** — Daily Briefing Audit Log
One row per daily run. Mirrors `PipelineRunRecord` for QA/audit traceability (FR-02.4.1 / FR-02.4.2). Caches rendered HTML/text so the dashboard can display today's briefing without re-running the pipeline.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `run_date_ist` | date | Unique; the IST date of the run |
| `domestic_override_active` | boolean | Whether FR-02.6 override triggered |
| `divergence_flag` | boolean | LLM signals conflict with GIFT gap? |
| `flat_override_triggered` | boolean | Was bias forced to FLAT? |
| `jargon_injections` | jsonb | List of jargon terms that were auto-defined |
| `entity_violations` | jsonb | List of entities that were genericized |
| `suppressed` | boolean | Run did not send (safety threshold exceeded) |
| `suppression_reason` | text | Why suppressed (e.g., "Entity violation count exceeded") |
| `bias_label` | text | `GAP_UP_STRONG` \| `GAP_UP_MILD` \| `FLAT` \| `GAP_DOWN_MILD` \| `GAP_DOWN_STRONG` |
| `gift_nifty_pct_change` | numeric(6, 3) | GIFT Nifty % change (used for bias reconciliation) |
| `briefing_html` | text | Cached rendered HTML briefing |
| `briefing_text` | text | Cached rendered plain-text briefing |
| `created_at` | timestamptz | When run completed |

**Indexes**:
- `idx_pipeline_runs_run_date` — fast lookup by date (descending for latest-first)

---

#### **Table 7: `send_log`** — Delivery Audit Trail
Per-recipient, per-channel delivery outcome. Tracks successes and failures across email, WhatsApp, Telegram.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `pipeline_run_id` | UUID | Foreign key to `pipeline_runs` |
| `subscriber_id` | UUID | Foreign key to `subscribers` (nullable on delete) |
| `recipient_email` | text | Recipient email address at send time |
| `channel` | text | `email` \| `whatsapp` \| `telegram` |
| `status` | text | `sent` \| `failed` |
| `error_message` | text | Reason for failure (if applicable) |
| `sent_at` | timestamptz | Timestamp of send attempt |

**Indexes**:
- `idx_send_log_run` — lookup by pipeline run
- `idx_send_log_recipient` — lookup by email
- `idx_send_log_subscriber` — lookup by subscriber
- `idx_send_log_channel` — filter by delivery channel

---

#### **Table 8: `password_resets`** — Password Reset Tokens
One-time tokens emailed during "Forgot Password" flow. Closes the gap from PRD v1.7 Section 5.8. Expires after 1 hour.

| Column | Type | Notes |
|--------|------|-------|
| `token` | text | Primary key |
| `subscriber_id` | UUID | Foreign key to `subscribers` |
| `created_at` | timestamptz | Issued at "forgot password" request |
| `expires_at` | timestamptz | Default: +1 hour |
| `used_at` | timestamptz | Set when new password submitted; single-use |

**Indexes**:
- `idx_password_resets_subscriber` — lookup by subscriber

---

#### **Table 9: `mfa_challenges`** — MFA Challenge Tokens
Issued by `POST /api/login` when password is correct AND `mfa_enabled=true`. Replaces the session token until user submits a valid TOTP/backup code. Expires after 5 minutes.

| Column | Type | Notes |
|--------|------|-------|
| `token` | text | Primary key |
| `subscriber_id` | UUID | Foreign key to `subscribers` |
| `created_at` | timestamptz | Issued after password check |
| `expires_at` | timestamptz | Default: +5 minutes |
| `consumed_at` | timestamptz | Set when TOTP verified; token becomes single-use |

**Constraint**: Ensures a correct password alone is never sufficient for an MFA-enabled account — password + TOTP are enforced as a strict sequence.

**Indexes**:
- `idx_mfa_challenges_subscriber` — lookup by subscriber

---

#### **Row-Level Security (RLS)**
All tables have RLS enabled defensively. Backend uses the `service_role` key (from GitHub Actions / Railway secrets), which bypasses RLS by design. If an `anon` key were ever exposed, **default-deny policies protect sensitive data** (password_hash, mfa_secret, etc.) from public access. No explicit policies are defined for anon/authenticated roles → guaranteed default-deny.

---

## 🚀 Deployment

### **Local Development**
```bash
pip install -r marketpulse/requirements.txt
export FLASK_APP=marketpulse.api.app
flask run --port 8000
```

### **Production (Railway)**
```bash
gunicorn marketpulse.api.app:app --workers 2 --bind 0.0.0.0:$PORT
```

### **Database Setup (Supabase)**
```bash
# Via Supabase SQL editor or CLI:
psql <supabase_connection_string> < marketpulse/persistence/schema.sql
```

### **Pipeline Scheduling (GitHub Actions)**
- The repository includes workflow files in both `.github/workflows/` and `marketpulse/.github/workflows/`. The authoritative schedules and job definitions are the YAML files in those directories.
- Notable schedule behaviour (current workflows):
  - Morning pre-render / briefing entry: scheduled at 00:30 UTC (06:00 IST). The scheduler script contains internal checkpoints and may sleep until later IST checkpoints (06:45 / 06:50 / 07:00) to align market/time-sensitive stages.
  - Record-close job: scheduled at 10:15 UTC (15:45 IST) to capture the official Nifty 50 close shortly after market close (15:30 IST).
  - Both workflows support manual `workflow_dispatch` with an optional `prev_close` input. Passing `prev_close=record` triggers the record-close job via dispatch.

See `.github/workflows/daily_briefing.yml` and `marketpulse/.github/workflows/daily_briefing.yml` for exact cron expressions and environment mappings.

---

## 📦 Dependencies

See `marketpulse/requirements.txt`:

- **`requests`** ≥2.31.0 — HTTP client for RSS, APIs, market data
- **`feedparser`** ≥6.0.10 — RSS feed parsing
- **`flask`** ≥3.0.0 — Web server
- **`gunicorn`** ≥21.2.0 — WSGI app server
- **`werkzeug`** ≥3.0.0 — password hashing
- **`pyotp`** ≥2.9.0 — TOTP-based MFA (RFC 6238, no external service)
- **`qrcode`** ≥8.0 — QR code generation for MFA enrollment
- **`Pillow`** ≥10.4.0 — image processing for QR codes

*(Optional, in root `requirements.txt`:)*
- **`zxcvbn`** 4.4.28 — password strength validation

---

## 🧪 Testing

Run unit tests:
```bash
python -m pytest marketpulse/tests/ -v
```

Key test areas:
- **Ingestion**: RSS feed parsing, event classification, time-window filtering
- **Analysis**: LLM prompt construction, response parsing, fallback neutrals
- **Bias**: Sector aggregation, reconciliation logic, divergence detection
- **Persistence**: subscriber auth, session lookup, audit logging
- **Delivery**: email/Telegram/WhatsApp dispatch logic, channel preferences

---

## 🔍 Key Concepts & PRD References

| Concept | Module | PRD Section |
|---------|--------|-------------|
| Event ingestion & normalization | `pipeline/ingestion.py` | FR-01.2 |
| Market snapshot capture | `pipeline/market_data.py` | FR-01.1 |
| LLM-driven sentiment analysis | `ai_engine/llm_client.py` | FR-02.2 |
| Sector aggregation | `ai_engine/bias_engine.py` | FR-02.3 |
| Bias reconciliation | `ai_engine/bias_engine.py` | FR-02.5 |
| Domestic override | `ai_engine/bias_engine.py` | FR-02.6 |
| Jargon/entity enforcement | `ai_engine/jargon_enforcer.py`, `entity_scanner.py` | FR-02.4.2 |
| Email templating | `email_system/render.py` | FR-03.1 |
| Multi-channel dispatch | `delivery/dispatcher.py` | FR-03.2 |
| Web dashboard & auth | `api/handlers.py` | FR-03.3 |

---

## 📋 Configuration

### **Environment Variables**

The workflows and code expect a combination of API keys and (optionally) SMTP configuration. Use `marketpulse/.env.example` as a template during development.

```bash
# Supabase Database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key  # used by GitHub Actions and server-side services

# LLM (primary used by workflows)
GEMINI_API_KEY=your-gemini-key   # repository workflows use GEMINI_API_KEY; ai_engine may also accept OPENAI_API_KEY
# Alternative: OPENAI_API_KEY=your-openai-key  # supported if configured in ai_engine/llm_client.py

# Email Delivery (either API or SMTP)
# If using an API provider like SendGrid/Resend, set the corresponding API key (optional):
SENDGRID_API_KEY=your-sendgrid-key
RESEND_API_KEY=your-resend-key

# If the workflows / email sender are configured to use SMTP, supply these instead:
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=smtp-user
SMTP_PASSWORD=smtp-password
EMAIL_FROM_ADDRESS=alerts@yourdomain.com

# Telegram Bot
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_BOT_USERNAME=your-bot-username

# WhatsApp via Twilio
TWILIO_ACCOUNT_SID=your-twilio-account-sid
TWILIO_AUTH_TOKEN=your-twilio-auth-token
TWILIO_WHATSAPP_FROM_NUMBER=+14155552671  # Twilio sandbox number

# Other runtime
PORT=8000
FLASK_ENV=production
LOG_LEVEL=INFO

# Optional: a comma-separated SUBSCRIBER_LIST (used by some workflows for small test deployments)
SUBSCRIBER_LIST="email1@example.com,email2@example.com"
```

Notes:
- The workflows reference `GEMINI_API_KEY` and `SUPABASE_SERVICE_ROLE_KEY` explicitly — ensure these are set in repository secrets for GitHub Actions runs.
- The code may accept `OPENAI_API_KEY` if you prefer OpenAI; check `ai_engine/llm_client.py` for supported providers.

See `marketpulse/.env.example` for a full template.

---

## 🛠️ Troubleshooting

### Pipeline hangs or times out
- Check `pipeline/orchestrator.py` stage timing vs. IST clock
- Verify RSS feeds are responding (common culprit: NSE maintenance windows)
- Check LLM API availability and rate limits

### Briefing not sent
- Verify `subscriber.status = 'active'` in database
- Check email/Telegram/WhatsApp credentials in `.env` / repository secrets
- Review `send_log` table for delivery errors:
  ```sql
  SELECT * FROM send_log WHERE status = 'failed' ORDER BY sent_at DESC LIMIT 10;
  ```
- Check `pipeline_runs.suppressed` flag — run may have been suppressed due to safety thresholds

### Email not received (bounces)
- Verify sender email domain is authenticated in SendGrid/Resend or SMTP provider
- Check `send_log.error_message` for SMTP errors
- Ensure subscriber email is not in spam filter

### MFA enrollment fails
- Verify QR code is being generated correctly (`/api/mfa/enroll/start` should return base64 PNG)
- Check that `mfa_secret` is stored in `subscribers` table
- Ensure time is synchronized on server (TOTP depends on server time)

### Telegram linking times out
- Verify `TELEGRAM_BOT_TOKEN` is correct and bot is active
- Check that `/start` command webhook is configured (`api.telegram.org/botXXX/setWebhook`)
- Review `telegram_links` table for expired or consumed tokens

### Jargon/entity violations detected
- Inspect `pipeline_runs.jargon_injections` / `pipeline_runs.entity_violations` audit logs
- Adjust `ai_engine/jargon_enforcer.py` or `entity_scanner.py` if false positives
- Update entity list in `ai_engine/entity_scanner.py` if needed

---

## 📄 License & Contributing

[License TBD] — for questions or issues, contact the maintainers.
