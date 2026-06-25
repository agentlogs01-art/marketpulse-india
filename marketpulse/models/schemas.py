"""
models/schemas.py

Core data models for MarketPulse India, matching the PRD's normalized
schemas exactly:
  - FR-01.2 Normalized Event Schema
  - FR-01.1 Market Instrument schema
  - FR-02.2 Sentiment analysis output schema
  - FR-02.3 / FR-02.5 Bias + reconciliation schema
  - FR-02.6 Domestic override schema

Using dataclasses (not pydantic) to keep the MVP dependency footprint
minimal per the <$100/mo infra constraint (Section 3) — no extra
runtime dependency required just to model data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums (kept as exact strings so they serialise cleanly to/from JSON and to
# the LLM prompt schema in FR-02.2)
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    CENTRAL_BANK = "CENTRAL_BANK"
    COMMODITY = "COMMODITY"
    GEOPOLITICAL = "GEOPOLITICAL"
    EARNINGS = "EARNINGS"
    MACRO_DATA = "MACRO_DATA"
    CURRENCY = "CURRENCY"
    REGULATORY = "REGULATORY"
    INDIA_DOMESTIC = "INDIA_DOMESTIC"  # Event Type 5 — referenced in FR-02.6
    OTHER = "OTHER"


class GeographicOrigin(str, Enum):
    US = "US"
    EU = "EU"
    CHINA = "CHINA"
    INDIA = "INDIA"
    GLOBAL = "GLOBAL"
    OTHER = "OTHER"


class Sentiment(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


class Direction(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


# MVP Sector Reduction (FR-02.2): exactly 5 sectors, no more, no less.
class Sector(str, Enum):
    BANKING = "BANKING"
    IT = "IT"
    AUTO = "AUTO"
    ENERGY = "ENERGY"
    FMCG = "FMCG"


class BiasLabel(str, Enum):
    GAP_UP_STRONG = "GAP_UP_STRONG"
    GAP_UP_MILD = "GAP_UP_MILD"
    FLAT = "FLAT"
    GAP_DOWN_MILD = "GAP_DOWN_MILD"
    GAP_DOWN_STRONG = "GAP_DOWN_STRONG"


# Delivery channels supported by the signup web app (webapp/) and the
# fan-out delivery layer (delivery/). A subscriber may enable more than
# one simultaneously -- see models.schemas.Subscriber.channels below and
# persistence/schema.sql's subscribers.channels text[] column.
class DeliveryChannel(str, Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"


class SubscriberStatus(str, Enum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    PAUSED = "paused"
    UNSUBSCRIBED = "unsubscribed"


# Plain-English label mapping (FR-02.3 "Note on label language") — the email
# template must use these, never the internal enum.
BIAS_PLAIN_ENGLISH = {
    BiasLabel.GAP_UP_STRONG: "\U0001F7E2 Market likely to open higher (>1%)",
    BiasLabel.GAP_UP_MILD: "\U0001F7E9 Market may open slightly higher",
    BiasLabel.FLAT: "\U0001F7E1 Market likely to open flat",
    BiasLabel.GAP_DOWN_MILD: "\U0001F7E7 Market may open slightly lower",
    BiasLabel.GAP_DOWN_STRONG: "\U0001F534 Market likely to open lower (>1%)",
}

BIAS_COLOR = {
    BiasLabel.GAP_UP_STRONG: "#0B6E2D",    # Dark Green
    BiasLabel.GAP_UP_MILD: "#5CB85C",      # Light Green
    BiasLabel.FLAT: "#E0B400",             # Yellow
    BiasLabel.GAP_DOWN_MILD: "#E07B00",    # Orange
    BiasLabel.GAP_DOWN_STRONG: "#C0392B",  # Red
}


# ---------------------------------------------------------------------------
# FR-01.2 — Normalized Event Schema
# ---------------------------------------------------------------------------

@dataclass
class NewsEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ingestion_timestamp: str = field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z"
    )
    source: str = ""
    source_url: str = ""
    headline: str = ""           # max 200 chars per PRD
    body_summary: str = ""       # max 500 chars per PRD
    event_type: EventType = EventType.OTHER
    geographic_origin: GeographicOrigin = GeographicOrigin.OTHER
    raw_body: str = ""
    credibility_score: float = 0.0
    is_scheduled_event: bool = False
    scheduled_time_utc: Optional[str] = None

    # Populated downstream by FR-02.2 sentiment analysis; not part of the
    # original ingestion schema but carried on the same object for
    # convenience through the pipeline.
    sentiment_intensity: Optional[int] = None  # 1-5, used by FR-02.6 trigger

    def __post_init__(self):
        self.headline = self.headline[:200]
        self.body_summary = self.body_summary[:500]

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["event_type"] = self.event_type.value
        d["geographic_origin"] = self.geographic_origin.value
        return d


# ---------------------------------------------------------------------------
# FR-01.1 — Market Instrument Snapshot
# ---------------------------------------------------------------------------

@dataclass
class InstrumentSnapshot:
    """One row of the Market Snapshot table (FR-01.1 / FR-03.1 Section 2)."""
    name: str
    value: float
    pct_change: float
    unit: str = ""               # e.g. "USD/barrel", "INR", "USD/oz"
    fetched_at_utc: str = field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z"
    )
    is_delayed: bool = False     # > 6 hours old at send time -> Data Delayed
    is_estimated: bool = False   # last-resort proxy used (e.g. Stooq ^NSEI)
    source: str = ""


# ---------------------------------------------------------------------------
# FR-02.2 — Sector Impact (LLM output, one per affected sector per event)
# ---------------------------------------------------------------------------

@dataclass
class SectorImpact:
    sector: Sector
    direction: Direction
    impact_magnitude: int            # 1-5
    rationale_plain_english: str     # max 60 words


@dataclass
class EventAnalysis:
    """FR-02.2 LLM output — one object per input event."""
    event_id: str
    overall_sentiment: Sentiment
    sentiment_intensity: int          # 1-5
    confidence: float                 # 0.0-1.0
    affected_sectors: list = field(default_factory=list)  # list[SectorImpact]
    nifty50_overall_bias: BiasLabel = BiasLabel.FLAT
    one_line_summary_for_beginner: str = ""  # max 25 words


# ---------------------------------------------------------------------------
# FR-02.3 — Aggregated per-sector scorecard (post weighted-average aggregation)
# ---------------------------------------------------------------------------

@dataclass
class SectorScorecard:
    sector: Sector
    direction: Direction
    impact_level: str                 # "Low" | "Medium" | "High" (FR-03.1 #6)
    rationale_plain_english: str
    is_mixed: bool = False
    score: float = 0.0                # weighted aggregate, internal use


# ---------------------------------------------------------------------------
# FR-02.5 / FR-02.6 — Bias reconciliation + domestic override
# ---------------------------------------------------------------------------

@dataclass
class GiftNiftySnapshot:
    last_traded_price: float
    pct_change_vs_prev_close: float
    prev_nifty_close: float
    captured_at_ist: str
    source: str = "nseifsc.com"
    is_fallback: bool = False         # True if Yahoo Finance GIFTY=F used
    is_estimated: bool = False        # True if Stooq ^NSEI last-resort proxy


@dataclass
class DomesticOverrideResult:
    active: bool = False
    trigger_event: Optional[NewsEvent] = None
    weights: dict = field(default_factory=dict)
    narrative_paragraph_2_override: Optional[str] = None


@dataclass
class ReconciliationResult:
    """Output of FR-02.5 Branch A/B logic — drives Paragraph 4 + bias badge."""
    bias_label: BiasLabel = BiasLabel.FLAT
    composite_score: float = 0.0
    flat_override_triggered: bool = False
    divergence_flag: bool = False
    divergence_direction: Optional[str] = None   # "higher" / "lower"
    divergence_event: Optional[str] = None
    divergence_signal: Optional[str] = None      # "conflicting" / "opposing"
    paragraph_4_token: str = ""                  # sentinel token
    top_signal_plain_english: str = ""
    domestic_override: Optional[DomesticOverrideResult] = None


# ---------------------------------------------------------------------------
# Pipeline run record (used across QA logging, entity scan, jargon injection)
# ---------------------------------------------------------------------------

@dataclass
class PipelineRunRecord:
    run_date_ist: str
    domestic_override_active: bool = False
    divergence_flag: bool = False
    flat_override_triggered: bool = False
    jargon_injections: list = field(default_factory=list)
    entity_violations: list = field(default_factory=list)
    suppressed: bool = False
    suppression_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Subscriber — backs persistence/schema.sql's `subscribers` table and is
# the shared domain object between webapp/, api/, and delivery/.
# ---------------------------------------------------------------------------

@dataclass
class Subscriber:
    id: Optional[str] = None
    email: Optional[str] = None
    mobile_number: Optional[str] = None
    password_hash: Optional[str] = None
    status: SubscriberStatus = SubscriberStatus.PENDING_VERIFICATION
    persona: str = "beginner"
    channels: list = field(default_factory=lambda: [DeliveryChannel.EMAIL.value])
    telegram_chat_id: Optional[str] = None
    whatsapp_number: Optional[str] = None
    created_at: Optional[str] = None
    verified_at: Optional[str] = None
    last_login_at: Optional[str] = None
    unsubscribed_at: Optional[str] = None

    def is_deliverable_on(self, channel: DeliveryChannel) -> bool:
        if self.status != SubscriberStatus.ACTIVE:
            return False
        if channel.value not in self.channels:
            return False
        if channel == DeliveryChannel.TELEGRAM and not self.telegram_chat_id:
            return False
        if channel == DeliveryChannel.WHATSAPP and not self.whatsapp_number:
            return False
        return True

    def to_public_dict(self) -> dict:
        """
        Serializes everything EXCEPT password_hash. Every API response
        that includes subscriber data must go through this rather than
        dataclasses.asdict() / __dict__ directly, so a future field added
        to this dataclass doesn't accidentally leak into a JSON response
        the way a raw dict dump would.
        """
        return {
            "id": self.id,
            "email": self.email,
            "mobile_number": self.mobile_number,
            "status": self.status.value if isinstance(self.status, SubscriberStatus) else self.status,
            "persona": self.persona,
            "channels": self.channels,
            "telegram_chat_id": self.telegram_chat_id,
            "whatsapp_number": self.whatsapp_number,
            "created_at": self.created_at,
            "verified_at": self.verified_at,
            "last_login_at": self.last_login_at,
            "unsubscribed_at": self.unsubscribed_at,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Subscriber":
        return cls(
            id=row.get("id"),
            email=row.get("email"),
            mobile_number=row.get("mobile_number"),
            password_hash=row.get("password_hash"),
            status=SubscriberStatus(row.get("status", "pending_verification")),
            persona=row.get("persona", "beginner"),
            channels=row.get("channels") or [DeliveryChannel.EMAIL.value],
            telegram_chat_id=row.get("telegram_chat_id"),
            whatsapp_number=row.get("whatsapp_number"),
            created_at=row.get("created_at"),
            verified_at=row.get("verified_at"),
            last_login_at=row.get("last_login_at"),
            unsubscribed_at=row.get("unsubscribed_at"),
        )


# ---------------------------------------------------------------------------
# Session — backs persistence/schema.sql's `sessions` table; issued at
# login, looked up on every authenticated request to the dashboard API.
# ---------------------------------------------------------------------------

@dataclass
class Session:
    token: str
    subscriber_id: str
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "Session":
        return cls(
            token=row["token"],
            subscriber_id=row["subscriber_id"],
            created_at=row.get("created_at"),
            expires_at=row.get("expires_at"),
            revoked_at=row.get("revoked_at"),
        )
