"""
utils/timeutils.py

Small, dependency-free IST timezone helpers. The PRD's entire critical
path (06:00 / 06:45 / 06:50 / 07:00) is specified in IST, but the
underlying infra (Railway, GitHub Actions) runs in UTC -- this module is
the single source of truth for that conversion so it's never duplicated
or fat-fingered across the pipeline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST_OFFSET = timedelta(hours=5, minutes=30)
IST = timezone(IST_OFFSET)

# The four critical-path checkpoints from the PRD, expressed as IST
# (hour, minute) tuples.
CHECKPOINTS_IST = {
    "pre_render": (6, 0),
    "snapshot": (6, 45),
    "assembly": (6, 50),
    "send": (7, 0),
}


def now_ist() -> datetime:
    return datetime.now(IST)


def utc_to_ist(dt_utc: datetime) -> datetime:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(IST)


def ist_checkpoint_today(name: str) -> datetime:
    """Return today's datetime (IST) for a named checkpoint, e.g. 'send'."""
    hour, minute = CHECKPOINTS_IST[name]
    today = now_ist().date()
    return datetime(today.year, today.month, today.day, hour, minute, tzinfo=IST)


def seconds_until_checkpoint(name: str) -> float:
    target = ist_checkpoint_today(name)
    return (target - now_ist()).total_seconds()


def is_past_checkpoint(name: str) -> bool:
    return seconds_until_checkpoint(name) <= 0
