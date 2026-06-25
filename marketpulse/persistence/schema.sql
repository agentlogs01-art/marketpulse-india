-- persistence/schema.sql
--
-- MarketPulse India MVP -- Supabase (Postgres) schema.
--
-- Designed for the Supabase FREE TIER (PRD Section 3 infra budget:
-- $16-26/mo total, Supabase contributing $0 at MVP scale -- 500MB
-- database, well within limits for a single-persona MVP subscriber
-- base). Run this once via the Supabase SQL editor or `supabase db push`.
--
-- Tables, each mapping directly to a persistence need called out in the
-- PRD / orchestrator:
--   1. subscribers         -- the user account: identity, credentials,
--                            channel preferences (Email/WhatsApp/Telegram)
--   2. sessions            -- server-side session tokens issued at login,
--                            backing the website's authenticated dashboard
--   3. email_verifications -- one-time verification tokens for the public
--                            signup form, so anyone can't subscribe an
--                            email/mobile they don't control
--   4. telegram_links      -- pending/confirmed Telegram chat_id bindings
--                            (the /start deep-link flow)
--   5. market_closes       -- previous-day official Nifty 50 close, persisted
--                            the evening before so the 06:45 IST snapshot
--                            step has a baseline without an extra live call
--   6. pipeline_runs       -- one row per daily run, mirrors PipelineRunRecord
--                            for QA/audit traceability (FR-02.4.1 / FR-02.4.2),
--                            and is also what the authenticated dashboard
--                            reads to render "today's briefing" in-browser
--   7. send_log            -- per-recipient, per-channel delivery outcome

-- ---------------------------------------------------------------------------
-- 1. subscribers
--
-- A subscriber is the account record. They identify by EITHER email or
-- mobile_number (at least one is required -- see check constraint below)
-- and authenticate with a password. `channels` is the set of delivery
-- channels currently active -- a person can enable more than one (e.g.
-- Email + Telegram) without creating a second account row. Signing in
-- on the website is a separate action from receiving the daily briefing
-- on a channel; either can be used independently of the other.
-- ---------------------------------------------------------------------------
create table if not exists subscribers (
    id                  uuid primary key default gen_random_uuid(),
    email               text unique,
    mobile_number       text unique,  -- E.164 format, e.g. +919876543210
    password_hash       text not null,
    status              text not null default 'pending_verification'
                            check (status in ('pending_verification', 'active', 'paused', 'unsubscribed')),
    persona             text not null default 'beginner'
                            check (persona in ('beginner')),  -- MVP: single persona only
    channels            text[] not null default array['email']::text[],
    telegram_chat_id    text unique,
    whatsapp_number     text unique,  -- delivery number; may differ from mobile_number (login id)
    created_at          timestamptz not null default now(),
    verified_at         timestamptz,
    last_login_at       timestamptz,
    unsubscribed_at     timestamptz,
    constraint channels_are_valid check (
        channels <@ array['email', 'whatsapp', 'telegram']::text[]
    ),
    constraint has_email_or_mobile check (
        email is not null or mobile_number is not null
    )
);

create index if not exists idx_subscribers_status on subscribers (status);
create index if not exists idx_subscribers_mobile_number on subscribers (mobile_number);
create index if not exists idx_subscribers_telegram_chat_id on subscribers (telegram_chat_id);
create index if not exists idx_subscribers_whatsapp_number on subscribers (whatsapp_number);

-- ---------------------------------------------------------------------------
-- 2. sessions
--
-- Backs the website's signed-in dashboard. A session token is issued at
-- login (POST /api/login) and stored client-side (the web app keeps it
-- in memory + a same-site cookie); every authenticated request looks the
-- token up here. Sessions expire and can be revoked (logout) without
-- touching the subscriber row itself.
-- ---------------------------------------------------------------------------
create table if not exists sessions (
    token           text primary key,
    subscriber_id   uuid not null references subscribers (id) on delete cascade,
    created_at      timestamptz not null default now(),
    expires_at      timestamptz not null default (now() + interval '30 days'),
    revoked_at      timestamptz
);

create index if not exists idx_sessions_subscriber on sessions (subscriber_id);

-- ---------------------------------------------------------------------------
-- 3. email_verifications
-- ---------------------------------------------------------------------------
create table if not exists email_verifications (
    token           text primary key,
    subscriber_id   uuid not null references subscribers (id) on delete cascade,
    created_at      timestamptz not null default now(),
    expires_at      timestamptz not null default (now() + interval '24 hours'),
    used_at         timestamptz
);

create index if not exists idx_email_verifications_subscriber on email_verifications (subscriber_id);

-- ---------------------------------------------------------------------------
-- 4. telegram_links
-- ---------------------------------------------------------------------------
create table if not exists telegram_links (
    link_code       text primary key,
    subscriber_id   uuid not null references subscribers (id) on delete cascade,
    created_at      timestamptz not null default now(),
    expires_at      timestamptz not null default (now() + interval '30 minutes'),
    consumed_at     timestamptz,
    chat_id         text
);

create index if not exists idx_telegram_links_subscriber on telegram_links (subscriber_id);

-- ---------------------------------------------------------------------------
-- 5. market_closes
-- ---------------------------------------------------------------------------
create table if not exists market_closes (
    trade_date      date primary key,
    nifty_close     numeric(10, 2) not null,
    source          text not null default 'NSE official',
    recorded_at     timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 6. pipeline_runs
--
-- `briefing_html` and `briefing_text` cache the rendered output for that
-- day's run -- this is what GET /api/briefing/latest reads to show the
-- signed-in dashboard "today's briefing" without re-running the pipeline
-- or re-deriving the render from scratch on every page view.
-- ---------------------------------------------------------------------------
create table if not exists pipeline_runs (
    id                          uuid primary key default gen_random_uuid(),
    run_date_ist                date not null unique,
    domestic_override_active   boolean not null default false,
    divergence_flag             boolean not null default false,
    flat_override_triggered     boolean not null default false,
    jargon_injections           jsonb not null default '[]'::jsonb,
    entity_violations           jsonb not null default '[]'::jsonb,
    suppressed                  boolean not null default false,
    suppression_reason          text,
    bias_label                  text,
    gift_nifty_pct_change       numeric(6, 3),
    briefing_html                text,
    briefing_text                text,
    created_at                  timestamptz not null default now()
);

create index if not exists idx_pipeline_runs_run_date on pipeline_runs (run_date_ist desc);

-- ---------------------------------------------------------------------------
-- 7. send_log
-- ---------------------------------------------------------------------------
create table if not exists send_log (
    id              uuid primary key default gen_random_uuid(),
    pipeline_run_id uuid references pipeline_runs (id) on delete cascade,
    subscriber_id   uuid references subscribers (id) on delete set null,
    recipient_email text,
    channel         text not null default 'email'
                        check (channel in ('email', 'whatsapp', 'telegram')),
    status          text not null check (status in ('sent', 'failed')),
    error_message   text,
    sent_at         timestamptz not null default now()
);

create index if not exists idx_send_log_run on send_log (pipeline_run_id);
create index if not exists idx_send_log_recipient on send_log (recipient_email);
create index if not exists idx_send_log_subscriber on send_log (subscriber_id);
create index if not exists idx_send_log_channel on send_log (channel);

-- ---------------------------------------------------------------------------
-- Row Level Security
--
-- The MVP backend talks to Supabase using the service_role key (set as a
-- GitHub Actions / Railway secret), which bypasses RLS by design. RLS is
-- still enabled here defensively so that if an anon/public key is ever
-- exposed, no public read/write access exists out of the box -- including
-- to password_hash, which must never be reachable from the browser.
--
-- The public web app (webapp/) does NOT talk to Supabase directly with an
-- anon key -- it calls the api/ serverless endpoints, which use the
-- service role key server-side and never return password_hash in any
-- response payload (see api/handlers.py's Subscriber-to-dict mapping).
-- ---------------------------------------------------------------------------
alter table subscribers enable row level security;
alter table sessions enable row level security;
alter table email_verifications enable row level security;
alter table telegram_links enable row level security;
alter table market_closes enable row level security;
alter table pipeline_runs enable row level security;
alter table send_log enable row level security;

-- No policies are defined for anon/authenticated roles -> default-deny.
-- Service-role key requests bypass RLS automatically.
