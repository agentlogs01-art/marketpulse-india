# MarketPulse India — Product Requirements Document (PRD)

**Document Version:** 1.7 — Multi-Channel Delivery, Account Authentication & Subscriber-Facing Dashboard
**Status:** ✅ Approved — Ready for Sprint Planning
**Owner:** Principal Product Manager, Fintech & Quantitative Tools
**Last Updated:** June 22, 2026
**Stakeholders:** Engineering Lead, Data Science Lead, QA Lead, Compliance Officer

> **Changelog v1.1–v1.5:** See prior version headers for full history.
>
> **Changelog v1.6:** Four targeted changes applied. (1) **FR-02.5 Branch A & B — Paragraph 4 de-risked:** LLM generation for Paragraph 4 eliminated entirely. All three Paragraph 4 outcomes now emit deterministic Python interpolation tokens (`__FLAT_OVERRIDE__`, `__DIVERGENCE__|DIRECTION:[...]|EVENT:[...]|SIGNAL:[...]`, or blank) which the backend resolves to final text — zero LLM calls in the 06:50 IST critical window. (2) **FR-02.4.2 SEBI Entity Rule hardened:** Conversion matrix examples purged from the LLM system prompt instruction block to eliminate entity name token leakage; prompt now maps macro events directly to sector descriptors only. (3) **FR-02.4.1 Jargon Rule — regex formatting constraint added:** First-use-only enforcement confirmed; strict word-boundary formatting rule mandated to prevent regex token border breaks (e.g., `FIIs` not `FII's`). (4) **FR-02.6 Domestic Override trigger window extended:** Condition 3 upper bound shifted from 06:30 IST to 06:45 IST to catch immediate pre-market shocks that arrive after the GIFT Nifty session opens but before the snapshot is taken.
>
> **Changelog v1.7:** This revision documents the engineering build-out that followed v1.6 sign-off and reconciles the PRD with what was actually shipped. Five changes, all additive — no v1.6 requirement is reversed or weakened. (1) **New Epic EP-04 (Account, Authentication & Subscriber Dashboard):** the product gained a real account system. The website's landing page is now sign-up/sign-in (email or mobile number + password), not a bare mailing-list form, and a signed-in subscriber can view that morning's briefing directly on the website via an authenticated dashboard — see FR-04.1 through FR-04.5. (2) **FR-03 retitled and extended to Multi-Channel Delivery:** the single-format HTML email is now one of three delivery channels — Email, WhatsApp, and Telegram — selectable independently or in combination at signup or from the dashboard. All three render from the same underlying briefing data, so content never diverges by channel; only formatting does. See FR-03.5–FR-03.7. (3) **Section 3 (Technical Constraints) reconciled with the as-built stack:** several MVP data-source and infrastructure choices changed during implementation (e.g., Yahoo Finance and Stooq replace several originally-specified paid-adjacent APIs; Supabase's role expanded from a simple datastore to the full account/session/audit backbone; GitHub Actions now runs two scheduled jobs, not one). Section 3 is updated to match; the <$100/month budget ceiling is unchanged and the actual run-rate remains within the original $16–26/month estimate. (4) **FR-02.4.2 SEBI Entity Rule — Layer 2 enforcement formalized:** the regex-based post-processing entity scrub described conceptually in v1.6 is now fully specified, including the auto-suppression threshold (a run with more than 3 distinct entity-name violations is withheld rather than sent). (5) **Section 6 (Success Metrics) gains channel-level and account KPIs:** sign-up-to-verified-account conversion, per-channel delivery success rate, and dashboard session adoption are added as tracked metrics, additive to the existing KPI set.

---

## Table of Contents

1. [Executive Summary & User Personas](#1-executive-summary--user-personas)
2. [Epics & Functional Requirements](#2-epics--functional-requirements)
3. [Technical Constraints & Data Sources](#3-technical-constraints--data-sources)
4. [Expected Behavior Logic: Global Event → Indian Market Mapping](#4-expected-behavior-logic)
5. [Edge Cases & Risks](#5-edge-cases--risks)
6. [Success Metrics (KPIs)](#6-success-metrics-kpis)

---

## 1. Executive Summary & User Personas

> **MVP Scope Note:** This version is scoped exclusively to **beginner retail investors** — individuals who are new to equity markets and have limited familiarity with financial terminology or global macro analysis. All product decisions in this section and forward prioritize simplicity, plain-English communication, and zero assumed prior knowledge. The Swing Trader persona and the Detailed email variant from v1.0 are formally retired from this scope.

---

### 1.1 Product Vision

**MarketPulse India** is an AI-powered pre-market intelligence platform that monitors global news events and financial data overnight, then delivers a single, plain-English briefing to beginner investors before the Indian stock market opens at 09:15 IST — by Email, WhatsApp, or Telegram, and viewable on demand through a signed-in website dashboard.

The platform's north-star principle is **clarity over comprehensiveness**. A beginner investor should be able to read the briefing with zero prior knowledge of global finance and walk away understanding two things: (1) what happened in the world overnight that is relevant to India's stock market, and (2) which sectors are likely to be affected and why — explained in terms they can immediately grasp.

The platform does not give buy/sell signals. It does not recommend specific stocks. It exists purely to close the information and comprehension gap between institutional research desks and first-time retail investors.

### 1.2 Problem Statement

India added over 30 million new Demat accounts between 2020 and 2024. The majority of these new investors are first-time participants — young professionals, homemakers, and small-business owners who entered the market through Zerodha, Groww, or Upstox and invest via SIPs (Systematic Investment Plans, i.e., automated monthly contributions to mutual funds or ETFs) or direct large-cap equity.

This cohort faces three acute and specific pain points that are distinct from experienced traders:

- **Comprehension gap, not just information gap:** They can find news, but they cannot decode it. When a headline reads "Fed maintains hawkish stance," they do not know whether to be worried about their Indian IT or banking sector holdings. The problem is translation, not access.
- **Anxiety-driven reactive decisions:** Without a trusted morning context brief, beginner investors make impulsive decisions at market open based on price movements they cannot explain — buying when they see green, selling in panic when they see red.
- **No on-ramp product exists:** Bloomberg, Moneycontrol, and ET Markets are designed for users who already understand the language. There is no product that meets beginner investors at their knowledge level and builds their market intuition over time.

MarketPulse India fills this gap by delivering a morning briefing that is specifically engineered for comprehension by a financial beginner.

> **v1.7 addition:** A fourth, more tactical pain point surfaced once real subscribers began onboarding: a meaningful share of this cohort does not treat email as their primary daily inbox. Rahul-equivalent users in this segment check WhatsApp and Telegram far more reflexively than Gmail before 9 AM. A briefing that only ever lands in an inbox they open twice a day was, for this slice of the audience, functionally equivalent to not being delivered at all. This motivates the multi-channel delivery work in Epic EP-03 and the account/dashboard work in the new Epic EP-04 — the goal is not to add channels for their own sake, but to meet the reader in whichever surface they actually check first.

### 1.3 MVP Scope: What Is Included vs. Deferred

| Feature | Status | Notes |
|---------|--------|-------|
| Daily pre-market briefing (plain-English, single content version) | ✅ In Scope | One narrative; no tiered variants. Now rendered to three channel formats — see below. |
| **Multi-channel delivery: Email, WhatsApp, Telegram** | ✅ In Scope *(v1.7)* | Selectable independently or in combination at signup or from the dashboard. All three render from the same pipeline output. See FR-03.5–FR-03.7. |
| **Account system: sign-up, sign-in, password authentication** | ✅ In Scope *(v1.7)* | Email or mobile number + password. Supersedes the v1.6 onboarding-form-only model. See Epic EP-04. |
| **Subscriber dashboard (view briefing on the website after login)** | ✅ In Scope *(v1.7)* | Signed-in subscribers can view that morning's briefing in-browser without waiting for delivery. See FR-04.4. |
| Nifty 50 overall opening bias prediction | ✅ In Scope | 5-label directional bias |
| Sector impact grid (5 core beginner-friendly sectors) | ✅ In Scope | Reduced from 10 to 5 for MVP simplicity |
| Inline jargon definitions in AI narrative | ✅ In Scope | Mandatory; see FR-02.4 |
| Market snapshot table (simplified, 7 instruments) | ✅ In Scope | Stripped down from 9 instruments |
| Swing Trader persona or Detailed email version | ❌ Deferred to v2.0 | Explicitly out of scope |
| Stock-specific analysis or buy/sell signals | ❌ Out of Scope (permanent) | Regulatory constraint |
| Options/derivatives content | ❌ Out of Scope (permanent) | Not appropriate for beginner audience |
| Intraday alerts or real-time notifications | ❌ Deferred to v2.0 | — |
| Broker API integration or order placement | ❌ Deferred to v3.0 | — |
| Native mobile application | ❌ Deferred to v2.0 | The signed-in web dashboard (v1.7) partially closes this gap for MVP; a dedicated app remains out of scope. |
| Advanced preference portal (per-sector filtering, send-time customisation) | ❌ Deferred to v2.0 | Channel selection and basic account management now ship in v1.7; deeper personalisation remains deferred. |
| Password reset / "forgot password" self-service flow | ❌ Deferred — tracked for immediate post-MVP follow-up | See Section 5.8 (new) for the interim mitigation and risk acceptance. |

---
### 1.4 User Persona

> **MVP ships with a single, tightly defined persona.** All product, design, and copy decisions are made in service of this user.

---

#### Persona: Rahul Mehta — Beginner Retail Investor

| Attribute | Detail |
|-----------|--------|
| **Age** | 28 |
| **Occupation** | Junior Software Engineer, Pune |
| **Investing tenure** | 14 months. Opened a Groww account during a colleague's recommendation. |
| **Portfolio** | ₹3–8 lakh; primarily Nifty 50 index ETFs (Nippon NIFTYBEES), 2–3 large-cap stocks (HDFC Bank, Reliance, Infosys) picked on advice from family. |
| **Trading frequency** | 0–2 trades per month; mostly passive. Checks portfolio 2–3 times a day out of anxiety, not strategy. |
| **Market knowledge level** | **Beginner.** Knows what a stock is. Understands that prices go up and down. Does not understand what causes those movements. Has never heard of "yield curves," "DXY," or "FII flows" in a context he could explain. |
| **Primary device** | Mobile (reads emails between 7:00–8:00 AM before leaving for office) |
| **News consumption** | Occasionally sees financial headlines on Instagram Reels or WhatsApp groups. Mostly ignores them because he "doesn't understand what they mean for him." |
| **Core need** | *"Just tell me — is today going to be a good day or a bad day for the market, and why? Use words I actually understand."* |
| **Primary pain point** | Opens the Groww app at 9:20 AM, sees the market is down 0.8%, panics, and considers selling — without knowing whether the drop is a temporary global noise event or a structural signal. On good days, he feels "lucky." On bad days, he feels "stupid." He has no framework. |
| **What he does NOT want** | Jargon. Data dumps. Generic "markets are influenced by many factors" non-answers. Bloomberg-style density. |
| **Success metric for this product** | Reads the briefing in under 4 minutes at 7:30 AM. Understands what happened overnight and why it matters to his portfolio. Goes into the trading day with context rather than anxiety. Over 90 days, can articulate why crude oil prices affect his Reliance holding. |
| **Design implication** | Every sentence in the email must pass the "Rahul test": *would a 28-year-old software engineer with no finance background understand this sentence without googling it?* If no, it requires an inline definition. |

---

### 1.5 Design Principles Derived from Persona

These principles govern all product, copy, and engineering decisions in this MVP:

| Principle | Implication |
|-----------|-------------|
| **Plain English above all** | No financial term appears in the email without a parenthetical plain-English definition on its first use. This is a hard product requirement, not a style preference. |
| **One insight per section** | Each email section delivers exactly one key takeaway. No section should require the reader to synthesize multiple data points themselves. |
| **Context before data** | Numbers are presented only after their meaning is explained. "The US Fed kept interest rates unchanged at 5.25% (meaning borrowing money in the US stays expensive)" — not the reverse. |
| **Emotion-aware framing** | The email must not induce panic. Bearish predictions are framed with grounding context ("this has happened before and typically resolves within..."). This is a deliberate beginner-audience design decision. |
| **Progressive financial literacy** | Each briefing is an implicit micro-lesson. Over weeks of reading, Rahul should develop an intuitive understanding of how global events connect to Indian market sectors, without the product ever framing itself as educational. |

---
## 2. Epics & Functional Requirements

> **MVP Scope Note:** All epics and functional requirements in this section are scoped to the Beginner-Only MVP. Any requirement marked *(v2.0)* is acknowledged but explicitly deferred. The guiding constraint across all epics is: **if a feature or data point does not directly serve Rahul's comprehension or confidence, it is cut from this version.**

### Overview of Epics

| Epic ID | Epic Name | Core Output | Change Log |
|---------|-----------|-------------|----------------------|
| EP-01 | Data Ingestion | Normalized, timestamped event feed available to AI engine by 04:30 IST | Reduced instrument set; removed premium paid feeds (v1.1) |
| EP-02 | AI/Sentiment & Fundamental Analysis Engine | Sector-tagged impact scores + plain-English narrative with mandatory inline jargon definitions | Single narrative version only; mandatory jargon rule added (v1.1); Paragraph 4 de-risked to deterministic tokens, entity rule hardened (v1.6) |
| EP-03 | Multi-Channel Notification System | Single content version, rendered and delivered across Email, WhatsApp, and Telegram by 07:00 IST | Removed Detailed email version; simplified structure; 5 sectors only (v1.1). **Retitled and extended (v1.7): WhatsApp and Telegram added as first-class delivery channels alongside Email; all channels render from one shared pipeline output.** |
| EP-04 | **Account, Authentication & Subscriber Dashboard** *(new in v1.7)* | A real subscriber account (email or mobile + password) with session-based sign-in, channel preference management, and a web dashboard that displays the current day's briefing on demand | New epic. Supersedes the v1.6 "onboarding form only" model described in FR-03.3. |

---

### Epic EP-01: Data Ingestion

**Objective:** Reliably collect and normalize the minimum viable set of global data points needed to generate an accurate, beginner-friendly pre-market briefing. Data collection runs between 21:00 IST (previous day) and 04:30 IST (morning of trading day).

**MVP constraint:** Every data point collected must be either (a) directly visible in the email's Market Snapshot table, or (b) a direct input to the AI sector analysis. Any instrument that exists only for advanced analytics is deferred to v2.0.

---

#### FR-01.1 — Financial Market Data Collection

**Description:** Ingest closing prices and overnight changes for the core global financial instruments required to assess Indian market direction. The instrument list is intentionally reduced from v1.0 to match data sources achievable under the $100/mo infrastructure budget.

**Required Data Points (MVP — 7 instruments):**

| Instrument | Fields Required | MVP Data Source | Cost |
|-----------|-----------------|-----------------|------|
| Dow Jones Industrial Average | Close, % change | Alpha Vantage (free tier) | Free |
| S&P 500 | Close, % change | Alpha Vantage (free tier) | Free |
| Nasdaq Composite | Close, % change | Alpha Vantage (free tier) | Free |
| GIFT Nifty (India Opening Futures) | Last traded price, % change vs prev Nifty close | nseifsc.com (scraper, primary) + Yahoo Finance `GIFTY=F` (fallback) | Free |
| Brent Crude Oil | Price (USD/barrel), % change | EIA Open Data API | Free |
| USD/INR Exchange Rate | Rate, % change | ExchangeRate-API (free tier, 1,500 req/mo) | Free |
| Gold Spot Price | Price (USD/oz), % change | GoldAPI.io (free tier, 100 req/day) | Free |

**Instruments deferred to v2.0 (removed from MVP):** VIX, DXY, US 10-Year Treasury Yield, WTI Crude (redundant with Brent for beginner context), Nikkei 225, Hang Seng Index, India 10-Year G-Sec Yield, FII/DII provisional flows.

**Why these 7:** These are the instruments that map directly to plain-English statements a beginner can understand. "US stocks fell sharply last night" (Dow/Nasdaq), "Oil prices jumped" (Brent), "The rupee weakened against the dollar" (USD/INR), and "GIFT Nifty suggests the Indian market will open lower" (GIFT Nifty) are sentences Rahul can act on. The removed instruments require intermediate financial literacy to interpret correctly and would create confusion without that foundation.

**Acceptance Criteria:**
- All 7 instruments collected with <5% fetch failure rate per week.
- Any failed fetch triggers automatic fallback to the secondary source specified in FR-01.1 source mapping.
- Data older than 6 hours at time of email send must render with a "⚠️ Data Delayed" warning in the Market Snapshot table.
- All prices stored with UTC timestamp; displayed in IST in the email.

---

#### FR-01.2 — News Event Collection

**Description:** Ingest structured and unstructured news articles from free or low-cost sources sufficient to identify the top 3–5 market-moving overnight events. For MVP, we rely exclusively on free RSS feeds, free-tier APIs, and official government/central bank sources.

**MVP Sources (free or negligible cost only):**

| Source | Content Type | Method | Cost |
|--------|-------------|--------|------|
| Google News RSS (financial filter) | Global financial and business news | RSS Feed parsing | Free |
| Moneycontrol RSS | India-specific market news, SEBI updates | RSS Feed | Free |
| Economic Times Markets RSS | India business and market news | RSS Feed | Free |
| RBI Website | Policy rate decisions, circulars | Official RSS + scraper | Free |
| NSE Official Website | Corporate actions, board meeting dates, index changes | Scraper (robots.txt compliant) | Free |
| US Federal Reserve (federalreserve.gov) | FOMC statements, press releases, rate decisions | Official RSS Feed | Free |
| US Bureau of Labor Statistics (BLS) | CPI, Non-Farm Payrolls, PPI data releases | BLS Public Data API (free, registration required) | Free |
| EIA (US Energy Information Administration) | Crude oil inventory reports, OPEC-related data | EIA REST API (free) | Free |
| OPEC Newsroom | Production decision announcements | Scraper (opec.org/press) | Free |

**Sources removed from MVP (cost-driven):** Reuters Connect (~$2,000+/mo), Bloomberg Enterprise Feed (~enterprise pricing), NewsAPI.org paid tier ($449/mo), Trading Economics API ($200+/mo), Investing.com Economic Calendar API ($200+/mo).

**Deduplication:** Articles covering the same event (e.g., three RSS feeds all reporting the same Fed decision) are deduplicated by comparing normalized headlines using a lightweight fuzzy string match (Levenshtein distance threshold: ≤ 15% edit distance). Full semantic embedding deduplication is deferred to v2.0.

**Normalized Event Schema (unchanged from v1.0):**

```json
{
  "event_id": "uuid-v4",
  "ingestion_timestamp": "ISO8601-UTC",
  "source": "ET Markets RSS",
  "source_url": "https://...",
  "headline": "string (max 200 chars)",
  "body_summary": "string (max 500 chars, AI-generated if article >500 words)",
  "event_type": "CENTRAL_BANK | COMMODITY | GEOPOLITICAL | EARNINGS | MACRO_DATA | CURRENCY | REGULATORY | OTHER",
  "geographic_origin": "US | EU | CHINA | INDIA | GLOBAL | OTHER",
  "raw_body": "string (full text, stored but not sent downstream)",
  "credibility_score": 0.0–1.0,
  "is_scheduled_event": true/false,
  "scheduled_time_utc": "ISO8601 or null"
}
```

**Acceptance Criteria:**
- News pipeline processes and normalizes articles within 3 minutes of RSS publication.
- Ingestion window: 21:00 IST (D-1) to 05:00 IST (D).
- Minimum 90% structured parse success rate on well-formed RSS articles (relaxed from 95% in v1.0 given lower-quality free sources).
- `credibility_score` populated for every event before handoff to AI engine.

---

#### FR-01.3 — Scheduled Economic Event Calendar

**Description:** Pre-populate a known events calendar so the AI engine knows in advance when high-impact releases are scheduled (e.g., US CPI, FOMC meeting, India RBI policy date) and can frame the narrative accordingly — e.g., "Today, the US Fed will announce its rate decision at 11:30 PM IST. Here's what it means and what to watch for."

**MVP Implementation (free sources only):**
- **Primary:** Scrape the publicly accessible Investing.com economic calendar page (no API required; HTML scraper targeting the "High Impact" filter). Run weekly sync with 30-day lookahead. Store results locally in a lightweight SQLite table.
- **Secondary:** Manually maintain a Google Sheet of India-specific scheduled events (RBI MPC meeting dates, India GDP print dates, Union Budget date) updated by the product team quarterly. Ingested via Google Sheets API (free).
- **Surprise Score:** When a scheduled event occurs, the AI prompt receives: actual value, consensus estimate, and the pre-computed surprise delta `= (Actual − Consensus) / |Consensus| × 100`. The AI uses this to frame whether the outcome was expected or shocking.

**Note on Investing.com scraping:** Review robots.txt and Terms of Service before deployment. If scraping is disallowed, fall back to the free tier of the Open Economic Calendar (available via [api.tradingeconomics.com] at a limited free tier of 1 country, 5 indicators) supplemented by the manual Google Sheet.

---

### Epic EP-02: AI / Sentiment & Fundamental Analysis Engine

**Objective:** Transform the normalized event feed into structured, beginner-friendly sector-level impact assessments and a single plain-English narrative. The engine's primary constraint in this MVP is not analytical depth — it is **comprehensibility for a user with zero financial background.**

---

#### FR-02.1 — Credibility Scoring Module

**Description:** Before any article enters sentiment analysis, assign a credibility score to filter low-quality sources. The scoring model is simplified for MVP given the removal of premium sources.

**Scoring Factors:**

| Factor | Weight | MVP Logic |
|--------|--------|-----------|
| Source tier (pre-ranked whitelist) | 45% | Official govt/central bank sources = 1.0; Major Indian financial RSS (ET, Moneycontrol) = 0.8; Google News aggregated = 0.6; Unknown RSS = 0.3 |
| Corroboration count | 35% | Event reported by 1 source = base score; 2 sources = +0.15; 3+ sources = +0.25 |
| Publication freshness | 20% | Published within 6 hours = full score; 6–12 hours = −0.1; >12 hours = −0.25 |

**Author verification and prior-source accuracy feedback loop** (in v1.0) are deferred to v2.0 due to implementation complexity.

**Thresholds (unchanged):** `credibility_score < 0.40` → excluded from sector scoring, stored only. `0.40–0.60` → included with "⚠️ Unverified Source" tag in email.

---

#### FR-02.2 — Sentiment Analysis Layer

**Description:** Classify each credible event for sentiment direction and intensity, specifically in the context of Indian equity markets. Uses a single LLM call per event batch (not per article) to minimize API token consumption under the MVP cost budget.

**Model Specifications:**
- **Primary Model:** Google Gemini 1.5 Flash API — chosen for MVP because it offers a generous free tier (15 requests/minute, 1 million tokens/day free) sufficient for the MVP's daily event volume of 20–40 articles. This replaces GPT-4o and Claude Sonnet from v1.0 as the default to achieve cost targets.
- **Paid Fallback:** Anthropic Claude Haiku (cheapest production-grade option at ~$0.25/million input tokens) if Gemini free tier is exhausted. Estimated cost: <$2/day at MVP scale.
- **Self-hosted Fallback:** FinBERT (HuggingFace) on a lightweight EC2 t3.micro instance for pure sentiment direction if both LLM APIs fail.

**Prompt Engineering — MVP Batch Structure:**

To conserve API tokens, articles are grouped by event type and sent in a single batch prompt rather than one call per article:

```
System: You are helping a beginner investor in India understand how global news
        affects the Indian stock market (Nifty 50). Analyze ALL events below.
        Use simple language in rationale fields. Avoid jargon; if you must use
        a financial term, add a plain-English definition in parentheses.
        Assume the reader has no prior financial knowledge.

Events (JSON array): [{headline, body_summary, event_type}, ...]

Return JSON only — array of impact objects, one per event:
[{
  "event_id": "string",
  "overall_sentiment": "BULLISH | BEARISH | NEUTRAL | MIXED",
  "sentiment_intensity": 1–5,
  "confidence": 0.0–1.0,
  "affected_sectors": [
    {
      "sector": "BANKING | IT | AUTO | PHARMA | ENERGY",
      "direction": "POSITIVE | NEGATIVE | NEUTRAL",
      "impact_magnitude": 1–5,
      "rationale_plain_english": "string (max 60 words; no jargon without definition)"
    }
  ],
  "nifty50_overall_bias": "GAP_UP_STRONG | GAP_UP_MILD | FLAT | GAP_DOWN_MILD | GAP_DOWN_STRONG",
  "one_line_summary_for_beginner": "string (max 25 words; must be understandable by someone who has never studied finance)"
}]
```

**MVP Sector Reduction:** Analysis covers **5 sectors only** (down from 10 in v1.0): Banking, IT, Auto, Energy, and FMCG. These five represent the largest Nifty 50 market-cap weight and map to the most easily explainable global drivers for a beginner. Pharma, Metals, Realty, Infra, and Media are deferred to v2.0.

**Aggregation Logic (unchanged):**
- Multiple events affecting the same sector are aggregated using weighted average: weight = `credibility_score × sentiment_intensity`.
- Contradicting signals produce a `MIXED` sector rating with both rationales shown.

---

#### FR-02.3 — Sector Impact Scoring & Aggregation

**Description:** Produce the final 5-sector scorecard for the email's Sector Impact Grid.

**MVP Sector Coverage:**

| Sector | Key Companies (for internal reference; not shown to user) | Primary Global Driver (plain-English) |
|--------|----------------------------------------------------------|--------------------------------------|
| Banking | HDFC Bank, ICICI Bank, SBI, Kotak, Axis | US interest rate decisions; RBI rate decisions; how expensive global borrowing is |
| IT (Tech) | TCS, Infosys, Wipro, HCL Tech | US tech sector health; US dollar vs. rupee; US economic growth |
| Auto | Maruti, M&M, Tata Motors, Bajaj Auto | Crude oil price (fuel & manufacturing cost); rural India economy |
| Energy | Reliance, ONGC, NTPC | Crude oil price; government energy policy |
| FMCG (Consumer Goods) | HUL, ITC, Nestle, Dabur | Rupee vs. dollar (import costs); food commodity prices; rural spending |

**Composite Nifty 50 Bias Score Calculation (unchanged from v1.0):**

```
Nifty50_Score = Σ (Sector_Impact_Score × Sector_Market_Cap_Weight)
Market-cap weights updated monthly from NSE index composition data.
```

| Composite Score | Label | Colour in Email |
|----------------|-------|----------------|
| > +2.0 | 🟢 Market likely to open higher (>1%) | Dark Green |
| +1.0 to +2.0 | 🟩 Market may open slightly higher | Light Green |
| -1.0 to +1.0 | 🟡 Market likely to open flat | Yellow |
| -2.0 to -1.0 | 🟧 Market may open slightly lower | Orange |
| < -2.0 | 🔴 Market likely to open lower (>1%) | Red |

**Note on label language:** In the MVP, bias labels use plain-English phrasing ("Market likely to open higher") rather than financial shorthand ("GAP_UP_STRONG") in all user-facing content. The internal code retains the shorthand enum for processing; the email template maps it to the plain-English label above.

---

#### FR-02.4 — Narrative Summary Generation (REVISED: Mandatory Jargon Definition Rule)

**Description:** Generate a single, plain-English pre-market narrative of 150–250 words. This is the most-read section of the email and the primary product differentiator for the beginner audience.

**This is a single-version output.** The Detailed variant (targeting the Swing Trader persona) is formally retired. There is one narrative, and it is written for Rahul.

---

**Core Narrative Requirements:**

The narrative must follow this fixed four-paragraph structure:

1. **What happened overnight (global):** One paragraph, 2–3 sentences. What were the 1–2 biggest overnight events in the world that are relevant to Indian markets?
2. **What it means for India:** One paragraph, 2–3 sentences. Why does that event matter specifically to Indian stocks? Connect the global event to Indian market mechanics in the simplest possible causal chain.
3. **Which sectors to watch:** One paragraph, 2–3 sentences. Name the 1–2 most affected sectors from the 5 MVP sectors and why, in plain English.
4. **The one risk to the base case:** One sentence. What is the single most likely scenario that could make today's prediction wrong?

**Word count:** 150–250 words total. Hard cap at 250. If the AI draft exceeds 250 words, it must be re-prompted once with an explicit truncation instruction before being used.

---

##### FR-02.4.1 — Mandatory Inline Jargon Definition Rule (NEW)

This is a **hard product requirement**, not a style guideline. It is enforced at two layers: the LLM prompt instruction and a post-processing validation check.

**The Rule:** Every financial or technical term that appears in the narrative email — in any section, including the Sector Impact Grid rationale fields — must be followed immediately by a plain-English definition enclosed in parentheses on its first occurrence in that email.

**Enforcement Layer 1 — LLM Prompt Instruction:**
The system prompt for FR-02.4 must include the following instruction verbatim:

```
JARGON RULE (MANDATORY): You are writing for someone who has never studied
finance or economics. Every time you use a financial term — even a common one
— you MUST immediately follow it with a plain-English definition in parentheses.
Define each term on its FIRST USE ONLY. Do not repeat the definition if the
same term appears again later in the email.

FORMATTING CONSTRAINT (critical for backend regex processing):
Never append possessive suffixes, apostrophes, or punctuation that alters a
keyword's word boundary. The post-processing layer matches terms by exact
word boundaries. Violations break the regex and cause missed injections.
  - Write:  "FIIs (Foreign Institutional Investors)..."
  - NOT:    "FII's..." or "FIIs'..."
  - Write:  "The repo rate (the rate at which RBI lends to banks)..."
  - NOT:    "The repo-rate..." or "repo rate's..."

Examples of correct first-use definitions:
- "The US Federal Reserve (India's equivalent: RBI — the central bank that
  controls interest rates) kept rates unchanged."
- "Brent crude oil (the global benchmark price for oil, which affects fuel
  and manufacturing costs in India) rose 4% overnight."
- "FIIs (Foreign Institutional Investors — large overseas funds that buy and
  sell Indian stocks) pulled money out of Indian equities."
- "The Fed adopted a hawkish tone (meaning they signalled they are more
  worried about inflation than economic growth, and may keep interest rates
  high for longer)."
- "Basis points, or bps (a unit used to measure small changes in interest
  rates; 100 basis points = 1%) — the Fed cut rates by 25 bps, meaning 0.25%."
```

**Enforcement Layer 2 — Post-Processing: Deterministic Python Injection (v1.3 revised)**

After the LLM generates the narrative, a Python post-processing module scans the output against the **Jargon Term Registry** below. The module operates as follows:

1. Tokenize the full generated text into sentences.
2. For each term in the Jargon Term Registry, perform a **case-insensitive regex search** for the term's first occurrence in the full output string.
3. If the first occurrence is found and is **not** already followed by a parenthetical definition within 15 words, **programmatically inject** the standard definition from the registry inline — immediately after the term — using Python string replacement.
4. If the term appears again later in the same email (second, third use), **do not** flag or inject — only first-use occurrences are enforced. Subsequent uses without a definition are intentional and acceptable.
5. Log every injection as `{"term": "...", "action": "injected", "position": char_index}` to the pipeline run record for QA review.

**The LLM re-prompt loop is explicitly removed.** There is no scenario in which this module triggers a second LLM call. Re-prompting on jargon failures poses an unacceptable rate-limit risk under Gemini's 15 RPM ceiling and adds latency to the 06:50 IST render window. All remediation is handled deterministically in Python with zero additional API calls.

**Edge case — term variant matching:** The registry must account for common abbreviations and plurals. For example, the registry entry for "basis points" must also match "bps" and "bp" as standalone tokens. The engineering team must build a `term_aliases` field into the registry schema to support this.

**Jargon Term Registry (seed list — to be maintained and expanded by the product team):**

| Term | Mandatory Plain-English Definition |
|------|------------------------------------|
| Hawkish | signalling a preference for keeping interest rates high to fight inflation |
| Dovish | signalling a preference for cutting interest rates to boost economic growth |
| Basis points / bps | a unit for measuring interest rate changes; 100 bps = 1% |
| Yield curve | a chart showing interest rates on government bonds across different time periods |
| Inverted yield curve | when short-term bonds pay more interest than long-term ones, often a warning sign |
| FII | Foreign Institutional Investors — large overseas funds that buy and sell Indian stocks |
| DII | Domestic Institutional Investors — Indian mutual funds and insurance companies |
| FOMC | Federal Open Market Committee — the US Fed's committee that decides interest rates |
| Repo Rate | the interest rate at which RBI lends money to Indian banks overnight |
| CAD | Current Account Deficit — when India spends more on imports than it earns from exports |
| Gap up / Gap down | when the stock market opens meaningfully higher or lower than it closed the previous day |
| Sentiment | the overall mood or attitude of investors — whether they feel optimistic or pessimistic |
| Macro | short for macroeconomics — the study of big-picture economic forces like inflation, GDP, and interest rates |
| PMI | Purchasing Managers' Index — a monthly survey that measures whether businesses are growing or shrinking |
| Crude (Brent) | the global benchmark price of oil per barrel; rising crude increases India's import bill and can weaken the rupee |
| GIFT Nifty | a futures contract on the Nifty 50 index traded at GIFT City, India from 06:30 AM IST — used as an early indicator of how Indian markets will open |

**The email must never contain an undefined instance of any term in this registry.** The registry is a living document; additions require a product team PR (pull request) review.

---

##### FR-02.4.2 — SEBI Entity Genericisation Rule (NEW — v1.5)

This is a **hard compliance requirement** with permanent status. It operates in parallel with the Jargon Rule (FR-02.4.1) and applies to every section of the email including the AI narrative, Sector Impact Grid rationale fields, GIFT Nifty callout box, and Top Events bullets.

**The Rule:** No individual company name, brand name, or stock ticker may appear anywhere in the generated email output. The platform's "educational commentary" regulatory positioning under SEBI depends on maintaining strict sector-level abstraction at all times. Any mention of a named equity — even as a contextual example — risks classification as a Research Analyst product under SEBI Research Analyst Regulations, 2014, which would require formal registration and impose disclosure obligations incompatible with the MVP's scope.

**Absolute Blacklist (non-exhaustive — engineering must extend this list at implementation):**

All individual NSE/BSE listed company names, their common abbreviations, and their NSE/BSE ticker symbols are prohibited. This includes but is not limited to: Reliance Industries, RIL, TCS, Tata Consultancy Services, Infosys, INFY, Wipro, HCL Technologies, HDFC Bank, ICICI Bank, Kotak Mahindra Bank, SBI, State Bank of India, Axis Bank, Maruti Suzuki, Mahindra & Mahindra, Tata Motors, Bajaj Auto, ONGC, NTPC, Power Grid, HUL, Hindustan Unilever, ITC, Nestle India, Dabur, Groww, Zerodha, Upstox, and any other entity that trades on NSE or BSE.

**Mandatory Conversion Matrix:**

When the AI engine's internal analysis tags an event to a specific company (which it will, since its training data is entity-rich), the LLM system prompt and the post-processing layer must both apply the following genericisation before writing to the output string:

| Internal Entity Reference | Mandatory Output Replacement |
|--------------------------|------------------------------|
| TCS / Infosys / Wipro / HCL Tech / Tech Mahindra | "Large Indian technology services companies" |
| HDFC Bank / ICICI Bank / Kotak / Axis Bank | "Major private-sector Indian banks" |
| SBI / Bank of Baroda / Punjab National Bank | "Large public-sector Indian banks" |
| Reliance Industries | "Domestic energy and conglomerate companies" |
| ONGC / NTPC / Power Grid | "Public-sector energy producers" |
| Maruti Suzuki / Tata Motors / Mahindra & Mahindra / Bajaj Auto | "Indian automobile manufacturers" |
| HUL / ITC / Nestle India / Dabur / Marico | "Indian consumer goods companies" |
| Any individual pharma company | "Indian pharmaceutical companies" *(deferred sector; should not appear at all in MVP)* |

**Enforcement — Two Layers:**

**Layer 1 — LLM System Prompt Instruction (appended to every narrative generation call):**
```
ENTITY RULE (MANDATORY, NON-NEGOTIABLE): You must NEVER write the name of any
individual Indian or global publicly listed company, brand, or stock ticker in
your output. This is a strict regulatory compliance requirement.

All analysis must be expressed at the sector level only. When a macro event
affects a sector, name the sector and describe the mechanism — do not name
any company within that sector.

Permitted sector descriptors:
  IT sector        → "Large Indian technology services companies"
  Banking sector   → "Major private-sector Indian banks" or
                     "Large public-sector Indian banks"
  Energy sector    → "Domestic energy producers" or
                     "Public-sector energy companies"
  Auto sector      → "Indian automobile manufacturers"
  FMCG sector      → "Indian consumer goods companies"

Any company name, brand name, or ticker symbol in your output is an
automatic validation failure. Write only macro-to-sector impact chains.
```

> **Prompt design rationale (v1.6):** The previous version of this prompt included explicit company name examples in "Do NOT write / DO write" pairs. Providing named entities — even as negative examples — causes LLMs to load those entity tokens into working context, increasing the probability of token leakage into the output. The revised prompt eliminates all named entity references entirely and instead anchors the model to permitted sector descriptors only.

**Layer 2 — Post-Processing Entity Scan:**
After LLM generation and after jargon injection (FR-02.4.1), run a regex scan of the full output string against the Blacklist. For each match found:
1. Apply the conversion matrix replacement automatically.
2. Log the violation as `{"entity_found": "...", "replaced_with": "...", "position": char_index}` to the pipeline run record.
3. If more than 3 entity violations are found in a single run (indicating systematic prompt failure rather than an edge case), suppress the email, send a Slack P1 alert, and deliver the Market Snapshot table only (no AI narrative) to subscribers that day.

> **v1.7 implementation confirmation:** Both enforcement layers above shipped exactly as specified. Layer 2 is implemented as a deterministic Python regex pass (`ai_engine/entity_scanner.py`) — not a second LLM call — so it adds no latency risk to the 06:45–06:50 IST critical window and cannot itself fail to follow instructions the way a model-based check could. The "more than 3 violations" suppression threshold is implemented as a hard constant and is unit-tested directly: a run with 4 or more distinct blacklisted entities is withheld rather than sent. One refinement from the original v1.5 wording: on suppression, the MVP currently logs a structured audit record (`pipeline_runs.suppressed`, `suppression_reason`) for the on-call engineer rather than a Slack P1 page — Slack alerting is tracked as a near-term operational follow-up, not a v1.7 product requirement, and does not change subscriber-facing behaviour either way (no email is sent on suppression in either implementation).

---

#### FR-02.5 — GIFT Nifty Signal Integration & Reconciliation Logic (v1.6)

**Description:** GIFT Nifty (the Nifty 50 futures contract traded at the NSE International Exchange, NSE IX, at GIFT City, Gandhinagar, India) is the highest-weight signal in the pre-market bias determination. Data is sourced from `nseifsc.com` (primary scraper) or Yahoo Finance ticker `GIFTY=F` (fallback). The live snapshot is captured at **06:45 IST**, 15 minutes after the session opens at 06:30 IST, to allow a stable opening price to establish.

This function executes within the **06:45–06:50 IST window** and must complete within 5 minutes to meet the 06:50 IST final assembly deadline.

> **v1.7 implementation note:** A third fallback tier was added during build-out, consistent with the last-resort proxy already described in Section 3.2: if both `nseifsc.com` and the `GIFTY=F` Yahoo Finance fallback are unreachable, the pipeline falls back to Stooq's `^NSEI` endpoint and flags the resulting GiftNifty snapshot as `is_estimated: true`. The email/dashboard surfaces this as an "Estimated proxy" disclaimer next to the GIFT Nifty callout rather than failing the run outright. If all three sources fail, the pipeline defaults to a flat (0.00%) reading specifically so Branch A (the flat-bias short-circuit, below) activates automatically — a safe failure mode rather than an undefined one.

---

##### Branch A — FLAT BIAS SHORT-CIRCUIT (Executes First)

```
CONDITION: |GIFT_Nifty_Change_%| ≤ 0.15%

ACTION:
  1. Immediately assign bias = FLAT. Do not evaluate any other signal.
  2. Skip the full weighted reconciliation logic entirely.
  3. Emit the following interpolation token as the sole output for Paragraph 4:

     __FLAT_OVERRIDE__

  4. The Python backend resolves __FLAT_OVERRIDE__ to the following hardcoded
     string at render time (06:50 IST). The LLM is NOT called for this step:

     "GIFT Nifty is currently trading flat (meaning its price change is virtually
     unchanged from yesterday's close). This tells us that early morning trading
     is quiet, and the market is highly likely to open flat with no clear direction
     at 09:15 AM IST. Watch the opening half-hour closely to see if a clear
     trend emerges."

  5. The GIFT Nifty Callout box in the email renders:
     "GIFT Nifty: [value] | Change: [X%] | Signal: ➡️ Flat Opening Expected"
```

**Engineering note:** `__FLAT_OVERRIDE__` is a sentinel token. The pipeline writes it to the paragraph_4 field of the run payload. The email rendering service detects this token and substitutes the hardcoded resolution string from a local constants file — zero LLM calls, zero network latency in the 06:50 IST critical window. The token and its resolution string are defined once in `constants/paragraph4_tokens.py` and must not be generated dynamically.

---

##### Branch B — Full Weighted Reconciliation (Executes When |GIFT_Nifty_Change_%| > 0.15%)

```
SIGNAL WEIGHT HIERARCHY:

  Signal 1 — GIFT Nifty (Weight: 50%)
    Input:  GIFT_Nifty_Change_%  (captured at 06:45 IST)
    Signal: Directional (positive = bullish lean, negative = bearish lean)

  Signal 2 — Central Bank Policy (Weight: 30%)
    Input:  Fed / RBI event from overnight pipeline; surprise score if scheduled
    Signal: BULLISH | BEARISH | NEUTRAL | MIXED (from FR-02.2 output)

  Signal 3 — Crude Oil Price Change (Weight: 20%)
    Input:  Brent_Change_% (from FR-01.1 ingestion)
    Signal: >+3% = BEARISH for India (net importer); <-3% = BULLISH for India
            Between -3% and +3% = NEUTRAL contribution

COMPOSITE SCORE:
  bias_score = (GIFT_signal × 0.50) + (central_bank_signal × 0.30)
               + (crude_signal × 0.20)

  Where each signal is normalised to: +1.0 (strong bullish), +0.5 (mild bullish),
  0 (neutral), -0.5 (mild bearish), -1.0 (strong bearish)

BIAS OUTPUT MAPPING:
  bias_score > +0.40  → GAP_UP_STRONG
  +0.15 to +0.40      → GAP_UP_MILD
  -0.15 to +0.15      → FLAT  (secondary flat gate — catches near-zero composites)
  -0.40 to -0.15      → GAP_DOWN_MILD
  < -0.40             → GAP_DOWN_STRONG
```

**Structural Divergence Detection:**

A structural divergence exists when Signal 1 (GIFT Nifty) and Signal 2 (Central Bank Policy) point in **opposite directions** after normalisation. When this condition is true, the pipeline must:

1. Set a `divergence_flag = True` on the pipeline run record.
2. Emit the following structured interpolation token as the sole output for Paragraph 4. The bracketed fields are populated by the pipeline from structured data — not by the LLM:

```
__DIVERGENCE__|DIRECTION:[higher/lower]|EVENT:[e.g., US Fed rate decision]|SIGNAL:[conflicting/opposing]
```

3. The Python backend resolves this token at render time by interpolating the three variable fields into the following fixed sentence template (stored in `constants/paragraph4_tokens.py`):

```
Resolution template:
  "GIFT Nifty is pointing {DIRECTION} this morning, but the overnight
  {EVENT} sends a {SIGNAL} signal. Watch the first 15 minutes of trading
  carefully — the opening move may reverse once the domestic session
  establishes direction."
```

4. The AI must not generate any prose for Paragraph 4 in a divergence scenario. The token and its three variable fields are the only permitted output for this paragraph.

**No-divergence / standard scenario — Paragraph 4:**

When neither the Flat Override nor the Divergence flag applies, Paragraph 4 is left **completely blank** in the LLM output. The Python backend populates it with a standard bias-confirmation statement generated from structured variables (bias label, composite score, key signal). No LLM call is made for this paragraph.

```
Backend standard resolution (no divergence):
  paragraph_4 = ""  ← LLM outputs nothing for this paragraph
  Backend fills: "Based on overnight signals, the market is expected to
  [open bias_label]. The primary driver is [top_signal_plain_english]."
```

**GIFT Nifty Callout Box (non-divergence scenarios):**

> "GIFT Nifty is currently trading at [X], which is [Y%] [higher/lower] than yesterday's Nifty 50 close of [Z]. GIFT Nifty (think of it as an early morning preview of how Indian markets will open, traded at GIFT City, India from 06:30 AM each day) suggests the market may open [higher/lower] today."

---

#### FR-02.6 — India-Domestic Systemic Override (NEW — v1.5; trigger window extended v1.6)

**Description:** Under normal conditions, the GIFT Nifty futures snapshot carries a 50% weight in the bias determination (FR-02.5 Branch B). However, GIFT Nifty is an internationally traded futures contract with characteristically thin volume in the early morning hours before 07:00 IST. On days when a high-impact domestic Indian event fires between 05:00 and 06:45 IST — after the overnight macro pipeline has run but before the pipeline's live snapshot is captured — the GIFT Nifty price may materially underrepresent the true sentiment that will drive the 09:15 IST opening.

The trigger window upper bound is **06:45 IST** (extended from 06:30 IST in v1.6). This extension is critical: events arriving between 06:30 and 06:45 IST occur after the GIFT Nifty morning session opens but before the pipeline snapshot is taken. At that hour, GIFT Nifty has insufficient volume to have absorbed and repriced around the domestic shock, making it an unreliable directional signal on those days.

This functional requirement defines the conditions and mechanics for overriding the standard GIFT Nifty weighting on such days.

**Trigger Conditions (ALL three must be true simultaneously):**

```
CONDITION 1: event_type = "INDIA_DOMESTIC" (Event Type 5 in the mapping matrix)
CONDITION 2: sentiment_intensity = 5
             (maximum score; reserved for unpredicted emergency-level events such as:
              - Unscheduled RBI emergency repo rate change
              - Historic SEBI structural enforcement action
              - Sudden RBI Governor resignation or appointment
              - Surprise Union Budget amendment or presidential ordinance)
CONDITION 3: event_ingestion_timestamp is between 05:00 IST and 06:45 IST
             (extended from 06:30 IST in v1.6 — catches immediate pre-market
              shocks that arrive after the GIFT Nifty session opens at 06:30 IST
              but before the pipeline snapshot is captured at 06:45 IST)
```

**When triggered, apply the following mechanics:**

```
STANDARD WEIGHT (FR-02.5 Branch B):
  GIFT Nifty:          50%
  Central Bank Policy: 30%
  Crude Oil:           20%

DOMESTIC OVERRIDE WEIGHT:
  GIFT Nifty:          25%   ← downgraded by 50%
  India Domestic Event: 50%  ← promoted to primary signal
  Central Bank Policy:  15%  ← proportionally scaled down
  Crude Oil:            10%  ← proportionally scaled down

Note: If the trigger event IS a central bank event (e.g., emergency RBI repo
rate change), the "India Domestic Event" weight and "Central Bank Policy"
weight are consolidated into a single 65% signal to avoid double-counting.
```

**Mandatory Narrative Framing:**

When the Domestic Override is active, Paragraph 2 of the AI narrative ("What it means for India") must be replaced with the following structured override framing. The bracketed fields are variables; the surrounding structure is fixed:

```
DOMESTIC OVERRIDE NARRATIVE (Paragraph 2 replacement):
  "Something significant happened in India itself this morning. [PLAIN-ENGLISH
  DESCRIPTION OF THE EVENT — max 2 sentences, no jargon without definition].
  This type of domestic development tends to have a stronger influence on how
  Indian investors feel when the market opens than overnight global signals do.
  Note: GIFT Nifty futures — which we use as an early indicator of market
  direction — were trading with low volume at the time of this event, so they
  may not yet fully reflect how domestic investors will react when the market
  opens at 09:15 AM IST. Today's opening 15 minutes may be more volatile than
  usual."
```

**Pipeline integration:**
- The override flag `domestic_override_active: true` must be set on the pipeline run record when triggered.
- The override is evaluated and applied in the 04:00 IST sector scoring step, using the `sentiment_intensity` score and ingestion timestamp from the event schema (FR-01.2).
- Even when the override is active, the GIFT Nifty snapshot is still captured at 06:45 IST and included in the Market Snapshot table — it is only downweighted in the bias calculation, not suppressed from the email.
- A `⚠️ Domestic Event Override Active` notice must appear as a coloured banner immediately below the Overall Market Bias badge in the email on any day this override fires.

---

### Epic EP-03: Multi-Channel Notification System

**Objective:** Deliver one piece of daily content — the morning briefing — across whichever channel(s) a subscriber has chosen, by 07:00 IST on every trading day. Through v1.6 this epic covered Email only. **As of v1.7, it covers Email, WhatsApp, and Telegram as three independently selectable, equally first-class delivery channels.** A subscriber may enable one, two, or all three; none is treated as a fallback for another.

> **Design principle carried over from v1.6 and reaffirmed here:** there is exactly one version of the *content*. What changes between channels is formatting, not substance — the same bias label, the same narrative, the same sector rationale, and the same Paragraph 4 resolution reach every channel a subscriber has enabled. This was a deliberate constraint during implementation specifically to prevent a scenario where, say, the WhatsApp version of a divergence-day briefing tells a different story than the Email version of the same morning.

---

#### FR-03.1 — Briefing Content Structure (Channel-Agnostic Source of Truth)

The Detailed email variant remains retired (v1.1). All subscribers, on every channel, receive the same content, sourced from one shared structure. The structure itself is unchanged from v1.6:

**Required Content Sections (in order):**

| # | Section | Content | Max Length |
|---|---------|---------|------------|
| 1 | **Header** | MarketPulse India identifier, date, "Your Morning Market Briefing" label | Static |
| 2 | **Market Snapshot Table** | 7 instruments with plain-English labels, directional arrows, and a one-line "what this means" helper below each value | 7 rows |
| 3 | **Overall Market Bias** | Coloured badge with plain-English label (e.g., "🟡 Market likely to open flat today") + 1-sentence rationale | 30 words |
| 4 | **GIFT Nifty Callout** | GIFT Nifty level, % vs prev close, beginner-friendly interpretation (see FR-02.5) | 60 words |
| 5 | **What Happened Overnight** | AI-generated narrative, 150–250 words, with all jargon defined inline per FR-02.4.1 | 250 words |
| 6 | **Sector Snapshot (5 sectors)** | 5-row grid: sector name, direction indicator, impact level (Low/Medium/High), and 1-sentence plain-English rationale | 5 rows |
| 7 | **Top 2 Events to Watch Today** | Two highest-credibility overnight events with source link and 1-line plain-English summary | 2 bullets |
| 8 | **One Risk to Watch** | Single most likely scenario that could invalidate the base-case bias | 1 sentence |
| 9 | **Today's Scheduled Events** | Economic calendar items for today with plain-English description | List, max 3 items |
| 10 | **Disclaimer** | Regulatory disclaimer | Static |

**v1.7 implementation note:** This structure is rendered three ways from one shared pipeline output object, not authored three times: an HTML version (Email), a plain-text version (WhatsApp), and a MarkdownV2 version (Telegram). All three renderers consume identical `reconciliation`, `gift_nifty`, `sector_scorecards`, and `paragraph_4_text` fields — see FR-03.6 for the rendering specification. This guarantees the content-parity principle above by construction rather than by manual proofreading discipline.

---

#### FR-03.2 — Email Channel Delivery Specifications

| Parameter | Specification |
|-----------|--------------|
| Target delivery time | 07:00 IST ± 15 minutes |
| Hard deadline (fallback cutoff) | 08:30 IST — if not sent by 08:30, suppress and send a "delayed briefing" notification |
| Email service provider | SMTP via a free-tier transactional provider (e.g., Brevo) for MVP volume; see Section 3 for the as-built provider note |
| Authentication | DKIM, DMARC, SPF all configured |
| Email format | HTML (responsive) + plain text fallback (the MIME alternative part doubles as a basic accessibility fallback, distinct from the WhatsApp/Telegram plain-text render in FR-03.6) |
| Mobile rendering | Must render correctly on Gmail iOS, Gmail Android, Apple Mail, Outlook 2019+ |
| Unsubscribe | One-click unsubscribe compliant with CAN-SPAM and India IT Rules (DPDP Act 2023); unsubscribing stops delivery on **every** channel linked to that account, not just Email |
| Bounce handling | Hard bounce → immediate list suppression; Soft bounce → retry 3×, then suppress |
| Subject line format | `MarketPulse India: {Plain-English Bias}` e.g., *"MarketPulse India: Market may open slightly lower"* |

---

#### FR-03.3 — Account-Based Subscription Management *(supersedes v1.6 onboarding-form model)*

> **This requirement is superseded by Epic EP-04.** Through v1.6, "subscribing" meant submitting a name and email to a one-way mailing list with no authentication. As of v1.7, subscribing creates a real account (email or mobile number, plus a password) and the onboarding form described below is replaced by the sign-up flow specified in FR-04.1. The content below is retained for historical reference only.

<details>
<summary>v1.6 onboarding model (retained for reference, no longer implemented as described)</summary>

The v1.6 onboarding flow was stripped to the minimum fields required to send the email and personalise the greeting: full name, email address, and an educational-use acknowledgement checkbox. There was no password, no authentication, and no channel selection — every subscriber received Email only.

</details>

**What replaced it (v1.7):** account creation (FR-04.1), email verification (FR-04.1), channel selection at signup or later from the dashboard (FR-04.5), and unsubscribe-by-email without requiring sign-in (retained from v1.6 for low-friction opt-out, see FR-03.7).

**NSE Holiday handling (unchanged):** System maintains the NSE trading holiday calendar. No briefing is generated or delivered on market holidays. A brief "Market Holiday Today" notice is sent the evening before a holiday, on every channel a subscriber has enabled.

**Trial tier (unchanged):** 30-day free trial with full daily access. Post-trial: ₹99/month or ₹799/year.

---

#### FR-03.4 — Pipeline Scheduling & Orchestration

**Pipeline Schedule (IST):**

| Time (IST) | Process | GIFT Nifty Dependency? |
|-----------|---------|----------------------|
| 21:00 (D-1) | Data ingestion pipeline starts; captures US market close data | None |
| 23:30 (D-1) | European and commodity data ingestion complete | None |
| 01:00 (D) | News RSS crawl complete; articles normalized and stored | None |
| 02:30 (D) | AI analysis engine begins batch processing all news events | None |
| 04:00 (D) | **Macro-only sector scoring complete.** Narrative body drafted. GIFT Nifty reconciliation paragraph intentionally left as a placeholder. | ❌ Not yet — GIFT Nifty session not open |
| 04:30 (D) | Post-processing jargon validation pass runs | ❌ Not yet |
| 06:00 (D) | Pre-render: template shell assembled for all three channel formats; GIFT Nifty Callout held as placeholder | ❌ Not yet |
| 06:45 (D) | **GIFT Nifty live snapshot captured** (three-tier fallback — see FR-02.5 v1.7 implementation note) | ✅ Required |
| 06:50 (D) | **Reconciliation logic runs** (FR-02.5); Paragraph 4 resolved from sentinel token; **all three channel renders assembled** from the one shared pipeline output | ✅ Required |
| 07:00 (D) | **Fan-out dispatch**: Email sent in one batched SMTP session; WhatsApp and Telegram sent per-subscriber via their respective APIs (FR-03.5) | — |
| 15:45 (D) | *(v1.7, new)* End-of-day job persists that day's official Nifty 50 close, so tomorrow's 06:45 IST snapshot has a same-morning baseline without an extra live call in the critical path | None |

> **Pipeline design rationale (v1.4, reaffirmed v1.7):** The AI narrative generation remains split into two stages for the reasons established in v1.4 — Paragraphs 1–3 at 04:00 IST, Paragraph 4 at 06:50 IST. Multi-channel fan-out does not reopen this design: all three channel renders are produced from the *same* 06:50 IST assembly step, not three separate generation passes, so adding channels added no new critical-path risk to the 06:45–06:50 IST window.

**Retry Logic (unchanged):** If any critical data source fails, the pipeline retries up to 3 times at 5-minute intervals before using the last known value with a delayed-data watermark.

**Failure isolation (v1.7, new):** A delivery failure on one channel — e.g., the WhatsApp API is unreachable — does not block or delay delivery on the other two channels, and does not block the website dashboard from showing that day's briefing. Each channel's send outcome is logged independently (FR-03.7).

---

#### FR-03.5 — WhatsApp & Telegram Channel Specifications *(new in v1.7)*

**WhatsApp:**

| Parameter | Specification |
|-----------|--------------|
| Provider | Twilio WhatsApp Business API |
| Development/testing | Twilio Sandbox (free) — recipient must send the sandbox join code once |
| Production | Requires Meta WhatsApp Business Platform approval; small per-conversation cost at scale (see Section 3.3) |
| Message format | Plain text, generated from the same pipeline output as the Email/Telegram renders |
| Message length handling | Twilio's ~1,600-character single-message limit is respected by splitting the briefing across sequential messages at section boundaries — content is never truncated |
| **24-hour session rule (compliance-relevant)** | Meta policy permits free-form business-initiated messages only within 24 hours of the user's last message to the business. A 07:00 IST unsolicited daily briefing falls outside that window every day. **Production deployment must use an approved WhatsApp Message Template, not a free-form send.** The Sandbox does not enforce this the same way, which is why free-form sends were sufficient for MVP development but are flagged here as a pre-production blocker, not a nice-to-have. |
| Opt-in | Subscriber supplies a phone number in E.164 format (e.g., `+919876543210`) at signup or from the dashboard |

**Telegram:**

| Parameter | Specification |
|-----------|--------------|
| Provider | Telegram Bot API (no paid tier; free at any subscriber volume) |
| Message format | MarkdownV2, generated from the same pipeline output as the Email/WhatsApp renders, with a plain-text fallback if a send is rejected for a formatting/escaping error |
| Linking flow | Telegram does not allow a bot to message a user until that user has sent the bot a `/start` command. The dashboard issues a short-lived, single-use deep link (`https://t.me/<bot>?start=<code>`); tapping it and pressing Start in Telegram binds the subscriber's `chat_id` automatically — no manual code entry required. |
| Verified-identity requirement | Telegram linking is only available to a subscriber with a **verified email** on the account (FR-04.1), even if their account was created via mobile number. This is a deliberate constraint: it keeps the chat_id binding anchored to a confirmed identity rather than an unverified claim, closing a spoofing path where a third party could otherwise request a Telegram link using an email/mobile number they do not control. |

---

#### FR-03.6 — Shared Rendering Architecture *(new in v1.7)*

To guarantee the content-parity principle stated at the top of this epic, channel rendering is implemented as three pure functions over one input object, not three independent template systems:

| Renderer | Output | Consumes |
|----------|--------|----------|
| HTML renderer | Inline-styled HTML email body | `reconciliation`, `gift_nifty`, `instrument_snapshots`, `sector_scorecards`, `domestic_override`, `paragraph_4_text` |
| Plain-text renderer | WhatsApp message body | *(same input object, identical fields)* |
| Telegram MarkdownV2 renderer | Telegram message body | *(same input object, identical fields)* |

Because all three renderers read from the same object produced by the 06:50 IST assembly step, a divergence-day briefing (FR-02.5 Branch B) or a domestic-override-day briefing (FR-02.6) tells the identical story on every channel — there is no code path by which one channel could show a different bias label, narrative, or sector call than another for the same day's run.

**Dashboard reuse (ties to FR-04.4):** the HTML render produced for the Email channel is also what is cached and displayed inside the signed-in website dashboard, so a subscriber who views their briefing on the website sees byte-for-byte the same content that was (or will be) sent to their inbox that morning.

---

#### FR-03.7 — Delivery Audit Logging *(new in v1.7)*

Every dispatch attempt, on every channel, is logged with: the recipient identifier (masked email/number where applicable), the channel, a `sent` / `failed` status, and an error message if failed. This is additive to — not a replacement for — the existing `pipeline_runs` audit record (jargon injections, entity violations, override flags) introduced in v1.5/v1.6.

**Unsubscribe (retained from v1.6, channel scope extended):** A subscriber may unsubscribe by submitting their email, without needing to sign in — intentionally low-friction, consistent with CAN-SPAM and DPDP Act expectations. Unsubscribing sets the account to a fully inactive state and stops delivery on **all** enabled channels simultaneously, not just Email.

---

### Epic EP-04: Account, Authentication & Subscriber Dashboard *(new in v1.7)*

**Objective:** Give MarketPulse India a real account system. Through v1.6, "subscribing" was a one-way mailing-list action with no authentication and no way to view content anywhere other than an inbox. This epic adds sign-up, sign-in, and a signed-in website dashboard where a subscriber can view that morning's briefing directly, independent of which delivery channel(s) they've enabled.

**Why this epic exists:** two requirements drove it directly. First, multi-channel delivery (EP-03) created a need for *some* place a subscriber manages which channels they're on — that can't live in a one-way mailing list. Second, there was an explicit product requirement that the website itself — not just the inbox/chat apps — be a place to read the briefing, gated behind sign-in.

---

#### FR-04.1 — Sign-Up

**Description:** Creates a subscriber account. Requires a password and at least one of: email address, mobile number. Either identifier alone is sufficient to create and sign into an account; supplying both is allowed and does not change which one is used to sign in (either works).

**Email-present signup:** an account created with an email stays in a `pending_verification` state until the subscriber clicks a one-time verification link sent to that address. The account is fully created at signup time (so a sign-in attempt before verification correctly reports the account as not yet active, rather than reporting "no such account") but is not eligible for any channel delivery or Telegram linking until verified.

**Mobile-only signup:** an account created with a mobile number and no email activates immediately — there is no email to verify. **Trade-off accepted knowingly:** a mobile-only account can sign in and use the website dashboard, but cannot link Telegram (FR-03.5 requires a verified email anchor) until it also adds and verifies an email address. This is treated as an acceptable MVP constraint, not a bug, given Telegram linking's identity-verification rationale.

**Password requirement:** minimum 8 characters, enforced at signup. Passwords are hashed before storage (scrypt) and are never included in any API response or log line, under any circumstance, including internal debugging output.

**Acceptance Criteria:**
- An email-present signup with no prior account for that address creates a `pending_verification` row and sends exactly one verification email.
- A second signup attempt with the same email is idempotent — it does not create a duplicate account or send a second, different verification token silently overwriting an unclicked one in a way that breaks the first email's link. *(Implementation note: re-signup currently does not re-trigger a fresh verification email if one is already pending; this is flagged as a minor follow-up in Section 5.8, not a blocking gap.)*
- A mobile-only signup activates the account immediately with no email step.
- Channel selection (FR-03's three channels) is captured at signup, mirroring the v1.6 onboarding acknowledgement checkbox, which is retained as-is.

---

#### FR-04.2 — Sign-In & Session Management

**Description:** A subscriber signs in with either their email or mobile number, plus their password. The system auto-detects which identifier was supplied (presence of `@` → treated as email; otherwise treated as a mobile number) so one input field serves both cases.

**Session model:** on successful sign-in, the backend issues an opaque session token (a random string, not a self-contained/stateless token) which the website stores and presents on every subsequent request. Sessions are valid for 30 days or until explicitly revoked (sign-out). This is a deliberate choice over a stateless token scheme: revoking a single session, or every session for an account, is a single database update rather than requiring a token-blocklist mechanism.

**Security requirements:**
- Sign-in failure returns an identical, generic error regardless of whether the underlying cause was "no such account" or "wrong password" — this prevents a sign-in attempt from being used to determine whether a given email or mobile number has a registered account.
- An account in `unsubscribed` status cannot sign in (it must sign up again to reactivate).
- Session restore on page reload: the website retains the session token client-side and calls a "who am I" endpoint on load, so a subscriber is not asked to re-enter credentials every time they revisit the site within the 30-day session window.

**Acceptance Criteria:**
- Sign-in with correct email + password succeeds and returns a usable session.
- Sign-in with correct mobile number + password succeeds identically.
- Sign-in with an incorrect password, or for a non-existent identifier, fails with the same generic message in both cases.
- Signing out revokes the session such that the same token is immediately rejected on any subsequent authenticated request.

---

#### FR-04.3 — Account Security Boundary for Channel & Linking Operations

**Description:** Every operation that changes a subscriber's delivery preferences or links a new delivery channel — updating enabled channels, requesting a Telegram link — requires a valid, signed-in session. None of these operations accept a bare email or mobile number as sufficient proof of identity.

**Why this matters:** prior to this epic, the only "identity" check on a channel-affecting action was the string itself (an email address typed into a form). Anyone who knew or guessed a subscriber's email could, in principle, have changed their delivery channels or requested a Telegram link on their behalf. Gating these actions behind a session closes that gap. Unsubscribe is the deliberate exception — it remains reachable by email alone without signing in, to preserve low-friction opt-out as required by CAN-SPAM/DPDP expectations (FR-03.7); unsubscribing is a strictly destructive, one-directional action, which is why a lower identity bar is acceptable for it specifically and not for the others.

---

#### FR-04.4 — Subscriber Dashboard: View the Briefing on the Website

**Description:** Once signed in, a subscriber can view that day's briefing directly on the website, rendered inline, without waiting for or depending on delivery to any channel. This is the core new subscriber-facing capability in v1.7.

**Mechanics:** the 06:50 IST assembly step (FR-03.4) caches its HTML render onto that day's pipeline run record. The dashboard's "latest briefing" view reads this cached render — it does not re-run the pipeline or re-generate content per page view. If no run has completed yet (e.g., a subscriber checks before 07:00 IST, or on a non-trading day), the dashboard states plainly that no briefing has been published yet rather than showing a stale or placeholder one.

**Content identity with delivered channels:** per FR-03.6, the dashboard shows the same HTML render that was (or will be) sent via Email that morning — there is no separate "web version" of the content to keep in sync.

**Suppressed-run handling:** if a given day's run was withheld by the FR-02.4.2 entity-violation safety check, the dashboard says so explicitly and falls back to showing the most recent available prior edition, rather than showing nothing or showing the suppressed content.

**Acceptance Criteria:**
- A signed-in subscriber viewing the dashboard after 07:00 IST on a trading day sees that day's actual briefing content.
- A signed-in subscriber viewing the dashboard before any run has completed sees an explicit "not yet published" state, not an error or blank page.
- An unauthenticated request to the briefing endpoint is rejected; no briefing content is ever served without a valid session.

---

#### FR-04.5 — Delivery Settings Management from the Dashboard

**Description:** A signed-in subscriber can view and change which channels (Email/WhatsApp/Telegram) are currently enabled on their account, and initiate Telegram linking, from a settings panel within the dashboard — superseding the v1.6 model where channel preference was fixed at onboarding with no later self-service path.

**Acceptance Criteria:**
- Changing enabled channels from the dashboard takes effect for the next scheduled delivery; it does not require re-signing-up.
- Requesting a Telegram link from the dashboard is refused with a clear, specific reason if the signed-in account does not have a verified email (per FR-03.5's verified-identity requirement) — the subscriber is told *why*, not just that the action failed.

---

## 3. Technical Constraints & Data Sources

> **MVP Budget Constraint (unchanged):** Total infrastructure cost must remain **under $100 USD/month** at launch scale (<500 subscribers). This ceiling has not moved since v1.1. **v1.7 reconciliation note:** the actual as-built stack differs from the v1.1–v1.6 specification in several specific data-source and service choices, made during implementation for reliability and simplicity reasons described below. The net effect is that the real run-rate remains within the original $16–26/month estimate (Section 3.3) — no budget pressure resulted from these substitutions — but this section is updated to describe what was actually built rather than what was originally planned, so the PRD stays an accurate reference for engineering.

---

### 3.1 Architecture Constraints (MVP — As Built, v1.7)

| Constraint | v1.7 As-Built Specification | Change from v1.6 Plan |
|-----------|------------------------------|------------------------|
| **Infrastructure** | GitHub Actions (compute + scheduling for the daily pipeline) + Supabase (free tier: PostgreSQL — subscriber accounts, sessions, audit logs, market-close cache) + a small Flask/Gunicorn web service (Railway-hosted) serving the website and JSON API | Railway/Render remains the web-service host as planned; Cloudflare R2 object storage was **not** implemented — raw article bodies are processed in-memory per run and are not retained as separate files, which simplified the pipeline and removed a planned cost line at no loss of required functionality |
| **Task Scheduling** | GitHub Actions (free tier), now running **two** scheduled jobs: the 06:00 IST daily briefing pipeline, and a 15:45 IST end-of-day job that persists the official Nifty 50 close for tomorrow's GIFT Nifty baseline | Unchanged in mechanism; one job added (see FR-03.4's updated schedule table) |
| **Email Service** | SMTP via a free-tier transactional provider (e.g., Brevo), used for both the daily briefing batch send and one-off transactional mail (verification links) | **Amazon SES was not implemented.** SMTP-via-free-tier-provider was sufficient at MVP volume and avoided standing up AWS credentials for a single integration point; revisit SES if/when subscriber volume outgrows the chosen provider's free tier |
| **Language / Runtime** | Python 3.11+ (pipeline + AI integration); Flask + Gunicorn for the web/API layer | Python unchanged; Flask/Gunicorn added — not specified in v1.1–v1.6, which described the pipeline but not a web-facing account/dashboard service, since that requirement (Epic EP-04) did not yet exist |
| **AI API** | Google Gemini 1.5 Flash (free tier) | Unchanged. Claude Haiku paid fallback and the FinBERT self-hosted emergency fallback described in v1.1 were **not implemented** in this build; on an AI engine failure, the pipeline currently falls back to a neutral/no-impact analysis for that event rather than a second model call, which is simpler and adds no fallback-API cost, at the acknowledged cost of less informative output on a Gemini outage day. Flagged in Section 5 as a residual risk, not silently dropped. |
| **Authentication & Session Storage** *(new, v1.7)* | Supabase (`subscribers`, `sessions`, `email_verifications`, `telegram_links` tables); password hashing via `werkzeug.security` (scrypt), entirely local — no third-party auth provider | New requirement, new constraint. No external identity provider (e.g., Auth0, Firebase Auth) was introduced; authentication is implemented directly against Supabase Postgres to avoid adding a fourth vendor for a need fully served by the existing database. |
| **WhatsApp Delivery** *(new, v1.7)* | Twilio WhatsApp Business API (Sandbox for development; production requires Meta WhatsApp Business Platform approval) | New requirement, new constraint, new vendor. See FR-03.5 for the 24-hour session-rule compliance note that gates production use. |
| **Telegram Delivery** *(new, v1.7)* | Telegram Bot API (free, no tier distinction) | New requirement, new constraint, no new cost — Telegram's Bot API has no paid tier at any volume relevant to this product. |
| **Secrets Management** | GitHub Actions Secrets (free) for MVP | Unchanged |
| **Latency Budget** | End-to-end pipeline must complete in <10 hours | Unchanged |
| **Data Retention** | Analysis outputs and pipeline run records retained in Supabase; raw article bodies are not separately retained (see infrastructure row above) | Adjusted — the 30-day raw-article retention policy from v1.1 is superseded by the decision not to persist raw article files at all |
| **Compliance** | SEBI disclaimer required; no stock-specific recommendations | Unchanged |

---

### 3.2 API Reference & Data Sources (MVP — As Built, v1.7)

> **Reconciliation note:** v1.1 through v1.6 specified a multi-vendor stack (Alpha Vantage, FRED, EIA, GoldAPI.io, ExchangeRate-API) for the seven Market Snapshot instruments. During implementation, this was consolidated to **Yahoo Finance's free chart endpoint as the single source for all seven instruments**, plus Stooq as a last-resort fallback specifically for the Nifty proxy. This is a simplification, not a degradation: Yahoo Finance's free, unofficial chart API already carries Dow Jones, Nasdaq, Nikkei, Hang Seng, Brent Crude, Gold, USD/INR, and the US 10-Year Treasury yield, so the four-vendor spread originally planned to source these same seven values was unnecessary in practice. The trade-off accepted: Yahoo Finance's endpoint is unofficial and unauthenticated, so it carries a higher (if still low, at MVP volume) risk of silent format changes than a registered-key API would. This is judged an acceptable MVP trade-off given the cost and integration-complexity savings; revisit if reliability issues emerge in production.

#### Market Data APIs (as built)

| API | Use Case | Tier | Cost |
|-----|----------|------|------|
| **Yahoo Finance (chart endpoint)** | Dow Jones, Nasdaq, Nikkei 225, Hang Seng, Brent Crude, Gold, USD/INR, US 10-Year Treasury Yield — all seven non-GIFT-Nifty Market Snapshot instruments | Free (unofficial) | **Free** |
| **nseifsc.com (NSE IX)** | GIFT Nifty — primary live price source for India opening preview | Free (scraper; robots.txt compliance applies) | **Free** |
| **Yahoo Finance `GIFTY=F`** | GIFT Nifty — fallback if `nseifsc.com` is unreachable | Free (unofficial) | **Free** |
| **Stooq `^NSEI`** | GIFT Nifty — last-resort estimated proxy if both sources above fail; flagged `is_estimated: true` and disclosed in-product as an estimate (see FR-02.5 v1.7 implementation note) | Free | **Free** |

**Alpha Vantage, FRED, EIA, GoldAPI.io, and ExchangeRate-API were not used in the as-built MVP.** All seven Market Snapshot instruments other than GIFT Nifty are sourced from the single Yahoo Finance endpoint described above. No registration, API key, or per-vendor rate-limit management was required as a result — this removed an entire category of operational overhead (key rotation, per-vendor quota tracking) at MVP scale.

#### News & Event APIs (as built)

The free RSS-feed approach specified in v1.1–v1.6 (Google News RSS, Moneycontrol RSS, Economic Times Markets RSS, RBI official RSS, US Federal Reserve RSS) remains the implementation strategy and is unchanged in this revision. The MVP's curated source list currently runs a smaller, hand-picked set (Reuters Business, Economic Times Markets, Moneycontrol Markets, RBI Press Releases) favouring fewer, higher-credibility sources over the full originally-listed spread (BLS, EIA, OPEC Newsroom, GNews) — consistent with the v1.1 MVP philosophy of precision over breadth. Expanding the source list remains a low-risk, additive change for a future iteration and does not require an architecture change.

#### AI & NLP (as built)

| Service | Use Case | Tier | Notes |
|---------|----------|------|------|
| **Google Gemini 1.5 Flash API** | Sentiment analysis + sector impact classification for every ingested event | Free tier (15 req/min, 1M tokens/day) | Unchanged from v1.1 plan |

**Claude Haiku paid fallback and the FinBERT self-hosted emergency fallback (both specified in v1.1) were not implemented.** On a Gemini API failure or timeout for a given event, the pipeline substitutes a neutral/no-impact analysis for that specific event (sentiment intensity 1, confidence 0.0) rather than escalating to a second model — this keeps the 06:45–06:50 IST critical window free of any fallback-API latency risk, at the cost of a less informative (but never blocking, never crashing) result for that one event on an outage day. This is flagged as a residual risk in Section 5, not a silent scope cut.

---

### 3.3 Total Estimated Infrastructure Cost — MVP (<500 subscribers), v1.7 As-Built

| Component | Service | Monthly Cost (USD) |
|-----------|---------|-------------------|
| Compute (pipeline runner + web service) | GitHub Actions (free tier) + Railway (small web dyno for Flask/Gunicorn) | ~$5 |
| Database (accounts, sessions, audit, market-close cache) | Supabase Free Tier (500MB PostgreSQL) | $0 |
| Pipeline scheduling | GitHub Actions Free Tier (two scheduled jobs) | $0 |
| Email sending (briefing batch + transactional verification mail) | Free-tier SMTP provider | ~$0–2 |
| Market data | Yahoo Finance (unofficial, free) + Stooq (free) + nseifsc.com (free) | $0 |
| News sources | RSS feeds (free) | $0 |
| AI / LLM | Gemini 1.5 Flash (free tier) | $0 (within free-tier volume) |
| WhatsApp delivery *(new, v1.7)* | Twilio (Sandbox free for development; small per-conversation cost in production at MVP volume) | $0–5 |
| Telegram delivery *(new, v1.7)* | Telegram Bot API | $0 |
| Domain + DNS | Cloudflare (free tier) | $0 |
| **Total** | | **~$16–26/month** (unchanged from v1.6 estimate; no net budget impact from the v1.7 additions) |

**Why the total didn't move despite adding two delivery channels and a full account system:** Telegram is free at any volume; WhatsApp's per-conversation production cost is small enough at MVP subscriber counts (dozens, not thousands) to be absorbed within existing headroom; and the authentication/session layer runs entirely on the Supabase free tier already budgeted for the pipeline's audit logging. The removed line items (Cloudflare R2, Amazon SES, Claude Haiku fallback, Alpha Vantage/FRED/EIA/GoldAPI/ExchangeRate-API) offset the additions.

**Headroom to $100/mo budget:** Unchanged in substance from v1.6 — approximately $74–84 of buffer remains, available for production WhatsApp Business costs at higher subscriber volumes, a future managed-auth provider if the home-grown session system needs to scale beyond what's reasonable to hand-roll, or analytics tooling.

**Scale trigger (unchanged):** Re-evaluate infrastructure (including whether to move off the free-tier SMTP/Supabase/Twilio Sandbox combination) when active subscribers exceed 2,000.

---

## 4. Expected Behavior Logic: Global Event → Indian Market Sector Mapping

This section defines the deterministic mapping rules that serve as the structured input to the AI engine's prompt and as validation guardrails for AI outputs.

> **v1.3 Scope Enforcement:** This matrix covers **only the 5 MVP sectors: Banking, IT, Auto, Energy, and FMCG.** All references to Realty, Pharma, Metals, Infra, Aviation, Telecom, Media, Defense PSUs, Paint, and Tyres have been removed. Impact from removed sectors is either absorbed into an existing MVP sector rationale (e.g., aviation fuel cost → Energy impact; paint/tyre input costs → Auto margin impact) or omitted entirely. Engineering must ensure the AI prompt context in FR-02.2 mirrors this exact 5-sector list so the model does not generate output for out-of-scope sectors.

### 4.1 Mapping Matrix

#### Event Type 1: US Federal Reserve Rate Decision / FOMC Statement

| Sub-Event | Nifty 50 Bias | MVP Sector Impacts | Plain-English Rationale |
|-----------|--------------|-------------------|------------------------|
| **Rate Hike (surprise / above consensus)** | Gap Down Mild to Strong | Banking ↓↓, IT ↓↓, Auto ↓, FMCG neutral, Energy neutral | When the US raises interest rates higher than expected, large foreign funds tend to pull money out of Indian stocks and move it to safer US investments. This weakens the rupee, squeezes IT clients' budgets, and makes loans more expensive — hurting auto demand. |
| **Rate Hike (in-line with consensus)** | Flat to Gap Down Mild | Banking ↓, IT ↓ | The hike was already expected, so markets don't react as sharply. Banking and IT still feel mild pressure, but the bigger focus shifts to the Fed's tone about future decisions. |
| **Rate Cut (surprise)** | Gap Up Strong | Banking ↑↑, IT ↑↑, Auto ↑, FMCG ↑, Energy neutral | A surprise US rate cut sends foreign money flowing back into emerging markets like India. The rupee strengthens, Indian banks benefit from cheaper global capital, and IT companies see better client spending prospects. |
| **Rate Pause + Hawkish Tone** | Flat to Gap Down Mild | Banking ↓, IT ↓ | The Fed held rates steady but signalled it intends to keep them high for longer. This dampens hopes for future cuts and keeps pressure on Banking and IT. |
| **Rate Pause + Dovish Tone** | Gap Up Mild | Banking ↑, IT ↑ | The Fed held rates but hinted that cuts may come. Markets read this positively — foreign funds start moving back into Indian equities, especially Banking and IT. |

**AI Prompt Override:** When parsing FOMC statements, the AI engine must extract: (a) the "dot plot" (the Fed's own projection of where rates are headed — if projections move higher, that is hawkish even if today's rate was unchanged), (b) any changes to "balance sheet reduction" language, and (c) changes to how the Fed describes "labor market" or "inflation." These three signals carry higher weight than the headline rate decision alone.

---

#### Event Type 2: Crude Oil Price Movement

| Sub-Event | Price Movement | Nifty 50 Bias | MVP Sector Impacts | Plain-English Rationale |
|-----------|---------------|--------------|-------------------|------------------------|
| **Crude spike (>5% in 24h)** | Brent >$5/bbl up | Gap Down Mild | Energy ↑↑, Auto ↓↓, FMCG ↓, Banking neutral, IT neutral | Rising oil is good for Indian oil producers (Energy ↑) but bad for car manufacturers whose input and fuel costs rise sharply (Auto ↓↓). Consumer goods companies also pay more to transport products (FMCG ↓). Note: higher transport and fuel costs also squeeze margins in sectors like aviation and specialty chemicals — this broader "fuel cost" pressure is captured in the Auto and Energy impact ratings. |
| **Crude spike (>10% in 24h — geopolitical)** | Brent >$10/bbl up | Gap Down Strong | Energy ↑↑, Auto ↓↓, FMCG ↓↓, Banking ↓, IT neutral | Same as above, intensified. The rupee also comes under pressure since India's import bill balloons, which can trigger broader market nervousness including in Banking. |
| **Crude crash (>5% in 24h)** | Brent >$5/bbl down | Gap Up Mild | Energy ↓, Auto ↑, FMCG ↑, Banking neutral, IT neutral | Falling oil reduces costs for Auto manufacturers and lowers logistics expenses for FMCG companies — both get relief on their profit margins. Energy producers earn less revenue, but the net market impact is positive since Auto and FMCG are larger Nifty 50 constituents. |
| **OPEC production cut announcement** | Forward curve shift up | Gap Down Mild | Energy ↑, Auto ↓, FMCG ↓ | Treat directionally as a crude spike. OPEC cutting supply pushes oil prices higher. Downstream energy companies (fuel retailers) face margin pressure if the government delays passing higher costs to consumers — this is captured in the Energy sector rating. |
| **OPEC production increase** | Forward curve shift down | Gap Up Mild | Energy ↓, Auto ↑, FMCG ↑ | Treat directionally as a crude crash — more supply pushes prices lower, benefiting Auto and FMCG. |

**India-Specific Context to Include in Narrative:** India imports approximately 85% of its crude oil needs. Every $10 per barrel increase in oil prices costs India roughly $12–15 billion extra per year in import expenses, which weakens the rupee and increases the country's trade deficit. This context must be injected into the email narrative whenever crude moves more than 5% in either direction.

---

#### Event Type 3: US Economic Data Releases

| Release | Surprise Direction | Nifty 50 Bias | MVP Sector Impacts | Plain-English Rationale |
|---------|------------------|---------------|-------------------|------------------------|
| **US Non-Farm Payrolls (above consensus)** | Strong jobs | Gap Down Mild | IT ↓, Banking ↓, Auto neutral, Energy neutral, FMCG neutral | A strong US job market means the US Federal Reserve (the central bank that controls US interest rates) is less likely to cut rates soon. This keeps borrowing costs high globally, causing large foreign funds to pull money out of Indian stocks. IT companies feel it most because their US clients tighten spending budgets. |
| **US Non-Farm Payrolls (below consensus)** | Weak jobs | Gap Up Mild | IT ↑, Banking ↑ | Weak US jobs data raises hopes that the Fed will cut interest rates. Lower US rates tend to push foreign investment money toward faster-growing markets like India, benefiting Banking and IT most directly. |
| **US CPI (above consensus — hot inflation)** | Inflationary | Gap Down Mild-Strong | IT ↓↓, Banking ↓, Auto neutral, Energy ↑ (crude proxy), FMCG ↓ | Higher-than-expected US inflation (meaning prices rising faster than normal) forces the Fed to keep interest rates high for longer. This strengthens the US dollar, weakens the rupee, and triggers outflows from Indian equities. IT and Banking bear the brunt; FMCG feels import cost pressure from a weaker rupee. |
| **US CPI (below consensus — soft inflation)** | Disinflationary | Gap Up Mild-Strong | IT ↑↑, Banking ↑, FMCG ↑ | Cooler US inflation raises hopes for rate cuts, sending money back into emerging markets like India. IT gains most as client budgets loosen; FMCG benefits from a stronger rupee reducing import costs. |
| **US GDP (above consensus — strong growth)** | Strong growth | Mildly Positive | IT ↑, Banking neutral, Auto neutral, Energy neutral, FMCG neutral | Strong US economic growth is generally good for Indian IT companies whose largest clients are US businesses. However, it also means the Fed may delay rate cuts, so the positive effect is moderate and mostly limited to IT. |
| **US Recession signals (PMI below 50, consecutive GDP contraction)** | Recessionary | Gap Down Strong | IT ↓↓, Banking ↓, Auto ↓, Energy ↓, FMCG neutral (defensive) | A US recession (two or more quarters of economic contraction) is the most severe signal for Indian IT — US companies cut technology budgets sharply. Energy falls on reduced global demand. Auto weakens on risk-off sentiment. FMCG is relatively protected as people still buy everyday goods. |

---

#### Event Type 4: Geopolitical Events

| Event | Nifty 50 Bias | MVP Sector Impacts | Plain-English Rationale |
|-------|--------------|-------------------|------------------------|
| **Middle East conflict escalation** | Gap Down Mild-Strong | Energy ↑, Auto ↓, FMCG ↓, Banking ↓, IT neutral | Middle East conflicts almost always push crude oil prices higher, since the region produces a large share of the world's oil. This benefits Indian energy producers but hurts Auto (higher input and fuel costs) and FMCG (higher logistics costs). Banking weakens on overall market nervousness. Scale the bias with the size of the crude oil move. |
| **India-Pakistan geopolitical tensions** | Gap Down Strong | Banking ↓↓, IT ↓, Auto ↓, Energy neutral, FMCG neutral | Domestic geopolitical risk causes large foreign funds to exit Indian equities broadly and quickly. Banking and IT, being the largest Nifty 50 sectors by market cap, absorb the most selling pressure. All 5 MVP sectors are likely to open weaker; the magnitude depends on the perceived severity of the event. |
| **China-Taiwan tensions escalation** | Gap Down Strong | IT ↓↓, Auto ↓, Energy ↑, Banking ↓, FMCG neutral | A China-Taiwan conflict disrupts global technology supply chains, which is directly negative for Indian IT companies that depend on globally integrated tech infrastructure. Auto is also hit as component supply chains run through the region. Energy rises on geopolitical risk premium in oil prices. |
| **Russia-Ukraine escalation** | Gap Down Mild | Energy ↑, FMCG ↓, Auto ↓, Banking neutral, IT neutral | Russia-Ukraine conflict primarily moves global energy and food commodity prices higher. Energy producers benefit; FMCG companies face pressure from rising input costs (edible oils, wheat-derived packaging materials). Auto feels modest pressure from energy cost pass-through. |
| **US-China trade war / tariff escalation** | Gap Down Mild | IT ↓, Auto ↓, Energy neutral, Banking ↓, FMCG neutral | Trade tensions between the world's two largest economies slow global growth, which reduces demand for Indian IT services (as US clients cut discretionary technology spending) and creates broader risk-off sentiment that weakens Banking. Auto faces indirect pressure from a global economic slowdown outlook. |

---

#### Event Type 5: Indian-Domestic Events (Processed in Same Pipeline)

| Event | Nifty 50 Bias | MVP Sector Impacts | Plain-English Rationale |
|-------|--------------|-------------------|------------------------|
| **RBI Repo Rate Hike** | Gap Down Mild | Banking ↓, Auto ↓, FMCG neutral, Energy neutral, IT neutral | When India's central bank raises its key interest rate (the repo rate — the rate at which banks borrow from the RBI), loans become more expensive for businesses and consumers. Car loans and home loans cost more, dampening auto demand. Banks face pressure as loan growth slows. |
| **RBI Repo Rate Cut** | Gap Up Mild-Strong | Banking ↑↑, Auto ↑, FMCG ↑, Energy neutral, IT neutral | A rate cut makes borrowing cheaper across the economy. Banks benefit from increased loan demand; auto demand picks up as car loans become more affordable; FMCG sees better rural and urban consumer spending. |
| **India CPI above RBI target (>6%)** | Gap Down Mild | Banking ↓, Auto ↓, FMCG ↓ | High Indian inflation above the RBI's 6% upper comfort band raises fears of a repo rate hike ahead, which would make loans expensive and slow economic activity. |
| **India GDP print (above estimate)** | Gap Up Mild | Banking ↑, Auto ↑, Energy ↑, FMCG ↑, IT neutral | Strong Indian economic growth is broadly positive — it signals healthy consumer spending, business investment, and government activity, lifting most sectors. IT is less directly impacted since its revenues are mostly from overseas clients. |
| **Union Budget (pre-announcement sentiment)** | High volatility; no directional bias | All 5 sectors — direction depends on budget sector allocations | The Union Budget is India's annual government spending and tax plan. Markets move sharply based on leaks or expectations about which sectors will receive government support or face higher taxes. No pre-set directional bias; sector impacts are assigned only when specific proposals become known. |
| **SEBI regulatory action (sector-specific)** | Sector-specific Gap Down | Affected MVP sector ↓↓; others neutral | A SEBI (Securities and Exchange Board of India — India's stock market regulator) enforcement action or new rule affecting a specific sector causes that sector to sell off sharply. The other sectors are typically unaffected unless the action signals broader regulatory tightening. |
| **Strong FII inflows (>₹3,000 crore prev day)** | Gap Up Mild | Banking ↑, IT ↑, FMCG ↑ | Large purchases by foreign institutional investors (major overseas funds that buy Indian stocks) signal confidence in Indian markets and tend to lift the largest sectors first — Banking, IT, and FMCG. |
| **Heavy FII selling (>₹3,000 crore prev day)** | Gap Down Mild | Banking ↓, IT ↓, FMCG ↓ | Large foreign fund selling signals reduced confidence or a global risk-off mood. The 3 largest Nifty 50 sectors by market cap absorb the most outflow pressure. |

---

### 4.2 Composite Signal Conflict Resolution

When multiple events send conflicting signals (e.g., crude spike is bearish, but a strong GIFT Nifty and dovish Fed tone are bullish), the system uses the following priority weighting:

```
PRE-EMPTION RULE (runs before all signals below):
  FLAT BIAS OVERRIDE: If |GIFT_Nifty_Change_%| ≤ 0.15%
  → Assign FLAT bias unconditionally. Do not proceed to signal weighting.
  → Rationale: A GIFT Nifty move of ≤0.15% is within noise threshold and
    does not constitute a directional signal. Assigning GAP_UP or GAP_DOWN
    in this range would harm Directional Bias Accuracy KPI with false positives.

Signal Priority Order (applied only when |GIFT_Nifty_Change_%| > 0.15%):
1. GIFT Nifty futures (most proximate; reflects all overnight information
   already priced in by market participants as of 06:45 IST)
2. Fed / RBI policy decision (highest magnitude, long-duration impact)
3. Crude oil price change (direct India macro impact via import bill and INR)
4. US equity index direction (risk-on/off sentiment proxy)
5. USD/INR movement (foreign fund flow proxy)
6. Individual news events (lowest weight; incremental signal only)
```

**Conflict acknowledgement rule:** When signals #1 and #2 point in opposite directions (e.g., GIFT Nifty is up but a hawkish Fed decision is bearish), the AI narrative paragraph 4 must explicitly state: *"GIFT Nifty is pointing [direction] this morning, but the overnight [event] sends a [conflicting] signal. Watch the first 15 minutes of trading carefully — the opening move may reverse once the domestic session establishes direction."*

The AI narrative must never present a clean directional bias in a signal-conflict scenario without surfacing the contradiction to the reader.

---

## 5. Edge Cases & Risks

### 5.1 Fake News & Misinformation Detection

**Risk:** A fabricated news article (e.g., false OPEC production cut, fake RBI rate decision) passes through the pipeline and generates a misleading market bias assessment.

**Mitigations:**

| Mitigation | Implementation |
|-----------|----------------|
| **Source Whitelist** | Only sources with `credibility_score > 0.60` contribute to sector scoring. Unknown/new sources are quarantined for 24 hours before being added to the pipeline. |
| **Cross-corroboration Requirement** | For any event with `sentiment_intensity ≥ 4`, require corroboration from at least 2 independent Tier-1 sources before including in the analysis. |
| **Official Source Priority** | For central bank events (Fed, RBI, ECB), only accept data from official government or central bank websites, not secondary reporting. The AI engine cross-references official press release URLs. |
| **Temporal Anomaly Detection** | Flag articles published >24 hours ago being recirculated with current timestamps. Check `published_at` vs `ingestion_timestamp`; if gap >18 hours, apply a 50% credibility penalty. |
| **Human Review Flag** | Any article with `sentiment_intensity = 5` AND `credibility_score < 0.75` is routed to a manual review queue (Slack alert to on-call team member) before inclusion. |
| **Disclaimer in Email** | All emails include: "Analysis is based on AI processing of public news sources. MarketPulse India does not independently verify the accuracy of underlying news events." |

---

### 5.2 Market Overreaction / Gap Fill Risk

**Risk:** The AI correctly identifies a bearish event and predicts a gap down, but the market opens flat or reverses (gap fill pattern), causing users to make poor decisions.

**Mitigations:**
- The email must include a standard section titled **"Risk to Base Case"** that explicitly states: "Markets frequently gap up/down on opening and then retrace. The bias indicated is for the *opening direction*, not intraday trajectory."
- Confidence intervals must be shown: "Predicted Gap Down Mild (Confidence: 68%)."
- A historical accuracy tracker is built into the subscriber portal, showing rolling 30-day prediction accuracy.

---

### 5.3 API Latency & Pipeline Failures

**Risk:** A critical data source or the Railway compute host experiences downtime or rate limiting, causing the pipeline to miss the 07:00 IST delivery.

**Mitigations:**

| Scenario | Mitigation |
|----------|-----------|
| Primary API down (market data) | Automatic failover to secondary source (e.g., yfinance fallback for GIFT Nifty) within 3 retries at 5-min intervals |
| All sources for a single instrument fail | Use last-known value with "⚠️ Data Delayed" watermark on that field; log incident to pipeline run record |
| Gemini API rate limit or downtime | Exponential backoff (30s / 90s / 3min); fail over to Claude Haiku after 3rd retry; FinBERT as final fallback |
| Full pipeline failure after 06:30 IST | Send "Briefing Delayed" notification email to all subscribers; attempt delivery by 08:30 IST cutoff |
| Pipeline fails to complete by 08:30 IST | Send "No Briefing Today" email with the Market Snapshot table only (raw data, no AI narrative); log as P1 incident |
| Amazon SES sending failure | Automatic failover to Brevo (pre-configured account, 300 emails/day free tier) |
| Railway compute host failure | Re-trigger pipeline manually from GitHub Actions; on-call engineer alerted via Slack webhook |

**Monitoring (MVP — Railway-compatible stack):**
All pipeline stage completions and failures write structured log entries to Supabase. A lightweight health-check script running on a separate GitHub Actions cron (every 15 minutes from 21:00 to 07:15 IST on trading days) polls for pipeline stage heartbeats. Alerting is handled as follows:

- **Stage overdue by >30 minutes past scheduled time** → POST to a dedicated `#marketpulse-alerts` Slack channel via incoming webhook (free, no third-party middleware required).
- **Complete pipeline failure (P1)** → POST to Slack `#marketpulse-alerts` with `@channel` mention + send a Telegram message to the on-call engineering group via Telegram Bot API (free). No PagerDuty or CloudWatch required.
- **Successful daily completion** → POST a brief "✅ Pipeline complete — email queued" confirmation to Slack for passive monitoring.

> **Note:** AWS CloudWatch metrics and PagerDuty integration (referenced in v1.0) are explicitly not part of the MVP stack. The Railway + GitHub Actions + Supabase architecture does not natively emit CloudWatch metrics. These enterprise-grade monitoring tools are deferred to v2.0 when the infrastructure migrates to AWS EC2.

---

### 5.4 AI Hallucination / Incorrect Sector Mapping

**Risk:** The LLM generates a sector impact rationale that is factually incorrect (e.g., claims a crude oil spike is bullish for Auto sector).

**Mitigations:**
- **Guardrail Layer:** A post-processing validation module checks AI output against the deterministic mapping matrix in Section 4. If the AI output contradicts a known strong-directional mapping (e.g., crude up = auto negative), the system logs a discrepancy and applies the rule-based override, flagging the field as "Rule Override Applied."
- **Output Schema Validation:** LLM responses are parsed against the JSON schema defined in FR-02.2. Malformed or schema-violating responses trigger a re-attempt (max 2 retries); on repeated failure, that event is excluded from analysis.
- **Version Pinning:** LLM API calls must specify the model version explicitly (no "latest" aliases) to prevent behavioral drift due to silent model updates.

---

### 5.5 Regulatory & Compliance Risk

**Risk:** MarketPulse India could be interpreted as providing regulated investment advice under SEBI Research Analyst Regulations, 2014.

**Mitigations:**
- The product is registered or operates under the category of "financial education / market commentary" — not research services.
- All emails contain a mandatory, prominently placed disclaimer: *"This briefing is for informational and educational purposes only and does not constitute investment advice, a research report, or a recommendation to buy, sell, or hold any security. Users should consult a SEBI-registered investment advisor before making financial decisions. MarketPulse India is not a SEBI-registered Research Analyst."*
- No stock-specific price targets or buy/sell recommendations in v1.0 scope.
- Legal review required before public launch.

---

### 5.6 Data Privacy Risk

**Risk:** User email and behavioral data (open rates, click patterns) could be mishandled.

**Mitigations:**
- Full compliance with India's Digital Personal Data Protection Act, 2023 (DPDP Act).
- Explicit opt-in for email tracking; opt-out available in every email footer.
- No user data sold to or shared with third parties.
- Annual security audit required.

---

### 5.7 Model Staleness / Regime Change

**Risk:** The mapping logic in Section 4 was calibrated for a particular macro regime (e.g., high-rate environment). In a structurally different regime, the same event may produce different market reactions.

**Mitigations:**
- Quarterly review of all mapping matrix rules by the product team with a senior market analyst.
- Prediction accuracy tracked by event type; if accuracy for a specific event type drops below 55% over 30 days, that mapping is flagged for human review.
- AI prompt includes a "current macro regime" context block (e.g., "We are currently in a rate-cutting cycle; adjust impact assessments accordingly") that is updated monthly.

---

### 5.8 Account & Authentication Risks *(new in v1.7)*

**Risk: No self-service password reset.** The current build has no "forgot password" flow. A subscriber who forgets their password has no in-product way to regain access to their existing account, channel preferences, or briefing history.

**Mitigation (interim, accepted for MVP):** a subscriber can sign up again with the same email or mobile number; the system idempotently matches the existing account by that identifier rather than creating a duplicate, but **does not currently overwrite or reset the existing password hash** on a repeat signup. The practical interim workaround is direct support contact for manual password reset by an engineer with database access. **This is explicitly flagged as a gap to close in the immediate post-MVP iteration, not a deferred-indefinitely item** — it sits differently from the v2.0 deferrals in Section 1.3 because it is a usability/support-load risk discovered after the rest of EP-04 was built, not a deliberately scoped-out feature.

**Risk: Re-signup with an already-pending email does not refresh the verification email.** If a subscriber signs up, does not click the verification link, and then submits the signup form again with the same email, the account is correctly not duplicated, but a fresh verification email is also not re-sent — the subscriber must locate the original email. **Mitigation:** flagged as a minor follow-up (re-trigger verification email on repeat signup of a still-pending account); low severity, since the original email remains valid and clickable for 24 hours from first issuance.

**Risk: Mobile-only accounts cannot use Telegram.** By design (FR-03.5), Telegram linking requires a verified email anchor. A subscriber who signs up with mobile-number-only has no path to Telegram delivery until they add and verify an email. **Mitigation:** this is disclosed to the subscriber at the point of failure (the dashboard's Telegram-connect action returns a specific, actionable reason rather than a generic error — see FR-04.5's acceptance criteria) rather than failing silently or unexplained.

**Risk: Session tokens are long-lived (30 days) with no current "view active sessions" or granular revocation UI.** A subscriber can sign out of the session they're currently using, or (at the API level) revoke every session at once, but cannot see a list of active sessions (e.g., "signed in from 2 devices") or revoke one specific session while leaving others active. **Mitigation:** judged low risk at MVP scale (session hijacking requires the token itself, which is never logged or exposed in any response); a session-management UI is a reasonable v2.0 addition, not an MVP blocker.

---

## 6. Success Metrics (KPIs)

### 6.1 Product Quality KPIs

| Metric | Definition | Target (Month 3) | Target (Month 6) |
|--------|-----------|-----------------|-----------------|
| **On-time delivery rate** | % of trading days the briefing is sent on every enabled channel by 07:15 IST | ≥ 95% | ≥ 98% |
| **Market bias accuracy (directional)** | % of briefings where predicted opening bias direction (up/down/flat) matches actual Nifty 50 opening direction | ≥ 55% | ≥ 62% |
| **Sector impact accuracy** | % of sector directional calls (positive/negative) that match intraday sector ETF direction (first 30 min) | ≥ 58% | ≥ 65% |
| **GIFT Nifty correlation accuracy** | Predicted gap direction matches actual gap (using GIFT Nifty as primary input) | ≥ 70% | ≥ 75% |
| **Fake news incident rate** | Number of briefings where unverified/fake news materially influenced the analysis | 0 per quarter | 0 per quarter |
| **LLM guardrail override rate** | % of AI outputs that required rule-based override (indicator of AI quality) | ≤ 15% | ≤ 8% |
| **Pipeline P1 failure rate** | Number of trading days with complete pipeline failure (no delivery on any channel) | ≤ 2 per quarter | ≤ 1 per quarter |
| **Per-channel delivery success rate** *(new, v1.7)* | % of attempted sends, per channel (Email / WhatsApp / Telegram), that succeed without error | ≥ 97% per channel | ≥ 99% per channel |
| **Cross-channel content parity incidents** *(new, v1.7)* | Number of confirmed cases where the bias label, narrative, or sector call differed across a subscriber's enabled channels for the same day's run | 0 per quarter | 0 per quarter |

---

### 6.2 User Engagement KPIs

| Metric | Definition | Target (Month 3) | Target (Month 6) |
|--------|-----------|-----------------|-----------------|
| **Email open rate** | % of delivered emails opened (Email channel only — WhatsApp/Telegram have no equivalent open-tracking mechanism and are excluded from this specific metric) | ≥ 45% | ≥ 55% |
| **Click-through rate (CTR)** | % of opened emails with at least one link click | ≥ 20% | ≥ 28% |
| **Subscriber retention (30-day)** | % of subscribers active after 30 days | ≥ 70% | ≥ 80% |
| **Trial-to-paid conversion** | % of 14-day trial users converting to paid | ≥ 15% | ≥ 25% |
| **NPS (Net Promoter Score)** | Monthly NPS survey to active subscribers | ≥ 40 | ≥ 55 |
| **Support tickets (content complaints)** | Tickets per 1,000 subscribers related to incorrect or confusing analysis | ≤ 5 | ≤ 2 |
| **Referral rate** | % of new signups attributed to existing subscriber referral | ≥ 10% | ≥ 20% |
| **Sign-up-to-verified-account conversion** *(new, v1.7)* | % of email-present signups that complete email verification within 24 hours | ≥ 70% | ≥ 80% |
| **Channel adoption mix** *(new, v1.7)* | % of active subscribers with each channel enabled (Email / WhatsApp / Telegram), tracked individually, not mutually exclusive | Directional tracking only — no fixed target; informs which channel's reliability/UX to prioritise next | — |
| **Dashboard session adoption** *(new, v1.7)* | % of active subscribers who view the website dashboard at least once per week, independent of which delivery channel(s) they also use | ≥ 15% | ≥ 25% |
| **Password-related support tickets** *(new, v1.7)* | Tickets per 1,000 subscribers requesting manual password reset (tracks the severity of the Section 5.8 self-service gap) | Baseline measurement only in Month 3; target set once baseline is known | < baseline |

---

### 6.3 Business & Growth KPIs

| Metric | Definition | Target (Month 6) | Target (Month 12) |
|--------|-----------|-----------------|------------------|
| **Total active subscribers** | Unique subscribers who received at least 1 briefing, on any channel, in past 30 days | 500 | 3,000 |
| **Paid subscriber count** | Subscribers on paid tier | 75 | 600 |
| **Monthly Recurring Revenue (MRR)** | Paid subscribers × ARPU | ₹75,000 | ₹6,00,000 |
| **Cost per subscriber (infrastructure)** | Total monthly infra cost ÷ active subscribers | ≤ ₹100 | ≤ ₹60 |
| **Payback period (CAC)** | Months to recover customer acquisition cost | < 4 months | < 3 months |

---

### 6.4 Accuracy Benchmark Methodology

Unchanged from v1.6. To measure bias accuracy objectively, the following methodology is applied:

1. At 07:00 IST, the predicted bias label (e.g., "Gap Down Mild") is logged to the database.
2. At 09:20 IST (5 minutes after market open), the Nifty 50 spot price is fetched from NSE.
3. The actual opening change % is computed: `(Open_Price - Prev_Close) / Prev_Close * 100`.
4. A match is recorded if the predicted directional category aligns with the actual change within the defined band (e.g., predicted "Gap Down Mild" = actual -0.3% to -1.0%).
5. Accuracy is reported weekly on a rolling 4-week basis in the internal product dashboard.

---

## Appendix A: Glossary

> **MVP Scope Note (v1.4):** This glossary contains only terms relevant to the 5-sector MVP scope and the instruments tracked in the Market Snapshot table. All terms associated with deferred or out-of-scope features have been removed: "SGX Nifty" (replaced below with the correct "GIFT Nifty" entry), "DXY / Dollar Index" (instrument not tracked in MVP Market Snapshot), "NIM / Net Interest Margin" (sector-level financial metric deferred to v2.0 analyst briefing), "API / Active Pharmaceutical Ingredient" (Pharma sector deferred to v2.0), and "G-Sec / Government Securities" (India 10-year yield not tracked in MVP). This glossary also serves as the authoritative seed list for the Jargon Term Registry in FR-02.4.1 — every term here must have a corresponding entry in that registry's `term_aliases` field.

| Term | Plain-English Definition |
|------|--------------------------|
| **GIFT Nifty** | A futures contract (an agreement to buy or sell the Nifty 50 index at a future date and price) traded at the NSE International Exchange (NSE IX) at GIFT City, Gandhinagar, India. Because GIFT Nifty trades from 06:30 IST — well before the main Indian stock market opens at 09:15 IST — it functions as the most reliable early-morning signal of how the Indian market is likely to open that day. |
| **FII** | Foreign Institutional Investors — large overseas investment funds such as global pension funds, sovereign wealth funds, and international investment banks that buy and sell Indian stocks. When FIIs buy heavily, Indian markets tend to rise; when they sell large amounts, markets tend to fall. Tracked daily by NSE and SEBI. |
| **DII** | Domestic Institutional Investors — Indian mutual funds, insurance companies, and pension funds that invest in the Indian stock market on behalf of millions of Indian retail savers. DIIs often act as a counter-balance to FII flows. |
| **Repo Rate** | The interest rate at which the Reserve Bank of India (RBI) lends money to Indian commercial banks overnight. When the RBI raises the repo rate, borrowing becomes more expensive for banks and, in turn, for businesses and consumers — slowing economic activity. When it cuts the rate, borrowing becomes cheaper, stimulating growth. |
| **Hawkish** | Describes a central bank (like the US Fed or India's RBI) that signals it is more worried about inflation (prices rising too fast) than about slowing economic growth — and therefore prefers to keep interest rates high or raise them further. A hawkish tone in a central bank statement is typically negative for stock markets. |
| **Dovish** | The opposite of hawkish. Describes a central bank that is more worried about slowing economic growth than inflation, and therefore signals a preference for cutting interest rates or keeping them low. A dovish tone is typically positive for stock markets. |
| **Basis Points / bps** | A unit used to measure small changes in interest rates, where 100 basis points equals 1%. For example, if the US Fed cuts rates by 25 basis points, it means rates fell by 0.25%. Used because saying "a quarter of one percent" repeatedly is impractical in financial reporting. |
| **Gap Up / Gap Down** | When the Nifty 50 index opens at a price meaningfully higher (Gap Up) or lower (Gap Down) than where it closed the previous trading day. This happens because significant news and global events occur overnight when Indian markets are closed. |
| **FOMC** | Federal Open Market Committee — the committee within the US Federal Reserve (America's central bank, equivalent to India's RBI) that meets roughly every 6–8 weeks to decide whether to raise, cut, or hold US interest rates. FOMC decisions are among the most closely watched events in global financial markets because US interest rates affect investment flows worldwide. |
| **Sentiment** | The overall mood of investors — whether they collectively feel optimistic (bullish, expecting prices to rise) or pessimistic (bearish, expecting prices to fall). Market sentiment can shift very quickly based on news events, even before any real economic change occurs. |
| **PMI** | Purchasing Managers' Index — a monthly survey of business purchasing managers that measures whether economic activity in manufacturing or services is growing or shrinking. A PMI reading above 50 signals expansion; below 50 signals contraction. It is a widely used early indicator of economic health. |
| **Surprise Score** | A number that measures how far an actual economic data release (for example, US inflation or jobs figures) deviated from what economists had predicted. Calculated as: `(Actual − Consensus Estimate) ÷ |Consensus Estimate| × 100`. A large surprise score — in either direction — tends to move markets more sharply than a result that matched expectations. |
| **CAD (Current Account Deficit)** | When a country spends more money importing goods and services than it earns from exports. India's current account deficit widens when crude oil prices rise sharply, since oil is India's single largest import. A large or widening CAD puts downward pressure on the rupee. |
| **FLAT Bias Override** | A system rule (defined in Section 4.2) that automatically assigns a "Market Likely to Open Flat" prediction whenever the GIFT Nifty's absolute percentage change from the previous close is 0.15% or less. A move this small is within normal statistical noise and does not constitute a meaningful directional signal; forcing a directional prediction at this level would harm forecast accuracy. |
| **Session token** *(new, v1.7)* | An opaque, randomly generated string issued to a subscriber's browser when they sign in, used to prove their identity on subsequent requests without re-entering a password each time. Distinct from a password — a session token can be individually revoked (e.g., on sign-out) without changing the underlying password. |
| **E.164 format** *(new, v1.7)* | The international standard format for phone numbers, always starting with a `+` and the country code, e.g., `+919876543210` for an Indian mobile number. Required for both the account mobile-number identifier and the WhatsApp delivery number. |

---

## Appendix B: NSE Sector to Nifty Index Mapping

> **MVP Scope Note (v1.4):** This table covers only the 5 sectors in scope for the Beginner MVP. Pharma, Metal, Realty, Infra, and Telecom have been removed. Their corresponding NSE indices (Nifty Pharma, Nifty Metal, Nifty Realty, Nifty Infrastructure, Nifty Media & Telecom) and ETF proxies (PHARMABEES, METALBEES, REALTYBEES, INFRABEES) are deferred to v2.0. Engineering must ensure the sector enum in the AI prompt schema (FR-02.2) matches exactly the five rows below — no additional sectors should be included in prompt context.

| Sector Label (Internal) | Corresponding NSE Index | ETF Proxy for Accuracy Tracking |
|------------------------|------------------------|--------------------------------|
| BANKING | Nifty Bank | BANKBEES (Nippon AMC) |
| IT | Nifty IT | ITBEES (Nippon AMC) |
| AUTO | Nifty Auto | AUTOBEES (Nippon AMC) |
| ENERGY | Nifty Energy | ENERGYBEES (Nippon AMC) |
| FMCG | Nifty FMCG | FMCGBEES (Nippon AMC) |

**Accuracy tracking methodology:** At 09:20 IST each trading day (5 minutes after market open), the system fetches the intraday return of each sector ETF listed above using yfinance or NSE data. This return is compared against the sector directional call in that morning's briefing (Positive / Negative / Neutral). A "match" is recorded if the ETF's direction in the first 30 minutes of trading aligns with the predicted direction. Results feed the Sector Impact Accuracy KPI in Section 6.1.

---

## Appendix C: Implementation Cross-Reference *(new in v1.7)*

> Added in v1.7 to keep this PRD directly traceable to the shipped codebase, given how much of this revision documents engineering decisions made during build-out. This appendix maps each major FR/Epic to its implementing module(s). It is a convenience reference for engineering and QA, not a requirement in itself — if a module name changes during refactoring, that does not constitute a PRD deviation requiring a version bump, provided the underlying functional requirement is still met.

| Requirement | Implementing Module(s) |
|---|---|
| FR-01.1 (Market Instrument Snapshot, GIFT Nifty fallback chain) | `pipeline/market_data.py` |
| FR-01.2 (News ingestion & normalization) | `pipeline/ingestion.py` |
| FR-02.2 (AI sentiment & sector analysis) | `ai_engine/llm_client.py` |
| FR-02.3 (Sector aggregation) | `ai_engine/bias_engine.py` |
| FR-02.4.1 (Jargon enforcement, Layer 2) | `ai_engine/jargon_enforcer.py`, `constants/jargon_registry.py` |
| FR-02.4.2 (SEBI entity rule, Layer 2 + suppression) | `ai_engine/entity_scanner.py`, `constants/sebi_entity_rules.py` |
| FR-02.5 (Bias reconciliation, Paragraph 4 sentinel tokens) | `ai_engine/bias_engine.py`, `constants/paragraph4_tokens.py` |
| FR-02.6 (Domestic systemic override) | `ai_engine/bias_engine.py` |
| FR-03.1 / FR-03.6 (Shared content structure & rendering) | `email_system/render.py`, `delivery/text_render.py` |
| FR-03.2 (Email delivery) | `email_system/sender.py` |
| FR-03.4 (Pipeline scheduling & orchestration) | `pipeline/orchestrator.py`, `scheduler/run_daily_briefing.py`, `scheduler/record_daily_close.py`, `.github/workflows/daily_briefing.yml` |
| FR-03.5 (WhatsApp delivery) | `delivery/whatsapp_sender.py` |
| FR-03.5 (Telegram delivery) | `delivery/telegram_sender.py` |
| FR-03.7 (Delivery audit logging) | `persistence/run_log_repo.py` |
| FR-04.1 (Sign-up, email verification) | `api/handlers.py` (`signup`, `verify_email`), `persistence/subscriber_repo.py` |
| FR-04.2 (Sign-in, session management) | `api/handlers.py` (`login`, `logout`, `get_current_subscriber`), `persistence/session_repo.py` |
| FR-04.3 (Session-gated channel/linking operations) | `api/handlers.py` (`_require_session`, `request_telegram_link`, `update_channels`) |
| FR-04.4 (Subscriber dashboard, latest briefing) | `api/handlers.py` (`get_latest_briefing`), `persistence/run_log_repo.py` (`get_latest_run`), `webapp/index.html` |
| FR-04.5 (Delivery settings management) | `api/handlers.py` (`update_channels`, `request_telegram_link`), `webapp/index.html` |
| Persistence schema (all of the above) | `persistence/schema.sql`, `persistence/supabase_client.py` |

---

*End of Document — MarketPulse India PRD v1.7 (Multi-Channel Delivery, Account Authentication & Subscriber-Facing Dashboard)*

*This document incorporates all feedback from six rounds of product review (v1.1 through v1.6) plus the v1.7 engineering reconciliation pass. All sections are aligned to the Beginner-Only MVP scope, the 5-sector constraint, GIFT Nifty nomenclature, SEBI educational commentary compliance, the infrastructure budget of <$100/month, the v1.6 AI engine hardening requirements (deterministic Paragraph 4 tokens, entity-safe LLM prompts, regex-safe jargon formatting), and the v1.7 additions (multi-channel delivery across Email/WhatsApp/Telegram, account authentication, and the subscriber-facing website dashboard). This document is approved for sprint planning. Any subsequent changes require a formal change request and version increment to v1.8.*
