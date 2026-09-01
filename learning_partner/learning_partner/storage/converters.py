"""Shared ORM <-> domain conversion helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional


def naive_utc(dt: datetime) -> datetime:
    """Store naive UTC (SQLite has no tz support)."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize a stored value back to timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def uid(value: uuid.UUID | str) -> str:
    return value if isinstance(value, str) else str(value)