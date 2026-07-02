# MarketPulse India — Core Application Module

**Version**: 1.6.0 | **Language**: Python (82.4%) | Built against PRD v1.6 (Critical Path De-Risk, SEBI Token Hardening & Override Extension)

---

## 📌 Overview

The `marketpulse/` module is the heart of the MarketPulse India platform — an **AI-powered pre-market intelligence system** delivering daily market briefings to Indian equity traders. It ingests overnight news from curated RSS sources, analyzes sentiment/sector impact via LLM, reconciles signals against GIFT Nifty snapshots, and dispatches briefings across Email, WhatsApp, and Telegram.

**Core Design Principle**: Graceful degradation at every stage. A single source failure or LLM timeout never blocks the 07:00 IST send — the pipeline falls back to neutral analysis or suppresses the run entirely rather than sending non-compliant briefings.

---

## 🏗️ Module Architecture

```
marketpulse/
├── __init__.py              # Package metadata (v1.6.0)
├── requirements.txt         # Core + Flask/Gunicorn for web app
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

The briefing generation follows a strict IST timeline, orchestrated by GitHub Actions:

### **Stage 1: Pre-Render (06:00 IST)**
- Static HTML template shell rendered; used as fallback if stage 2 fails

### **Stage 2: Snapshot (06:45 IST)** — `pipeline/market_data.py`
- Fetch **GIFT Nifty** (^NSEI) from NSE iFC API; fall back to Yahoo Finance → Stooq
- Capture **instrument snapshots** (commodities, currency, indices) from external APIs
- Flag stale data (>6 hours old) for transparency in briefing

### **Stage 3: Ingestion** — `pipeline/ingestion.py` (any time, before assembly)
- Pull from 10 curated RSS sources (NSE, RBI, Reuters, MarketWatch, etc.)
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
  - **Email**: SendGrid / Resend API
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

### **Database** — Supabase (PostgreSQL) — `persistence/schema.sql`

Tables:
- `subscribers` — accounts + MFA secrets + backup codes
- `sessions` — active auth tokens
- `pipeline_runs` — audit log (briefing date, bias label, GIFT %, suppressed?)
- `send_results` — delivery audit (email bounces, Telegram sent count, etc.)
- `market_closes` — official Nifty 50 daily closes (for bias reconciliation)

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

### **Pipeline Scheduling (GitHub Actions)**
- **Cron 1**: 06:45 IST → `marketpulse.scheduler.record_daily_close` (fetch Nifty close)
- **Cron 2**: 07:00 IST → `marketpulse.scheduler.run_daily_briefing --skip-wait` (full pipeline)

See `scheduler/` for entry points.

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

Key environment variables:
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_KEY` — Supabase anon key
- `SENDGRID_API_KEY` or `RESEND_API_KEY` — Email delivery
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` — WhatsApp via Twilio
- `OPENAI_API_KEY` — LLM endpoint (if using OpenAI)
- `PORT` — Flask app port (default 8000)

See `.env.example` for a template.

---

## 🛠️ Troubleshooting

### Pipeline hangs or times out
- Check `pipeline/orchestrator.py` stage timing vs. IST clock
- Verify RSS feeds are responding (common culprit: NSE maintenance windows)
- Check LLM API availability

### Briefing not sent
- Verify `subscriber.status == "active"`
- Check email/Telegram/WhatsApp credentials in `.env`
- Review `send_results` table in Supabase for delivery errors

### Jargon/entity violations detected
- Inspect `record.jargon_injections` / `record.entity_violations` in `pipeline_runs` audit log
- Adjust `ai_engine/jargon_enforcer.py` or `entity_scanner.py` if false positives

---

## 📄 License & Contributing

[License TBD] — for questions or issues, contact the maintainers.