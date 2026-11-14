from __future__ import annotations

import os
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "Asia/Dushanbe"


def _setting(name: str) -> str | None:
    value = os.getenv(name)
    if value and value.strip():
        return value.strip()
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, candidate = line.partition("=")
        if separator and key.strip() == name:
            return candidate.strip().strip('"').strip("'") or None
    return None


def get_app_timezone() -> ZoneInfo:
    tz_name = _setting("APP_TIMEZONE") or _setting("TIMEZONE") or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def now_local() -> datetime:
    return datetime.now(get_app_timezone())


def to_db_datetime(value: datetime | None) -> datetime | None:
    """Convert a period boundary to UTC before comparing it with stored timestamps.

    Timestamps are written by the database (``CURRENT_TIMESTAMP`` / ``now()``) in UTC.
    SQLite compares datetimes as text and ignores the offset, so a boundary in local
    time (Asia/Dushanbe, UTC+5) used to shift every report by five hours.  For
    PostgreSQL an aware UTC value is equivalent, so behaviour there is unchanged.
    Naive values are treated as local application time.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=get_app_timezone())
    return value.astimezone(timezone.utc)


def local_day_start(day: date) -> datetime:
    return to_db_datetime(datetime.combine(day, time.min, tzinfo=get_app_timezone()))


def local_day_end(day: date) -> datetime:
    return to_db_datetime(datetime.combine(day, time.max, tzinfo=get_app_timezone()))
