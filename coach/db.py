"""Single database module for the whole app.

One SQLite file (``data/coach.db``) holds both the coach's small raw-sqlite
tables (``users``, ``auth_tokens``, ``active_sessions``) and the learner
model's SQLAlchemy tables. ``sqlite_conn()`` owns the raw-sqlite DDL and is
used by ``backend/auth.py`` and ``backend/dependencies.py``; ``Base`` /
``create_session_factory()`` own the SQLAlchemy side (engine, declarative
base, ORM converters) and are used by the ``learner`` package, whose table
models live next to their repositories. ``create_schema()`` /
``learner_engine()`` / ``learner_session()`` bridge the two worlds.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "coach.db"

_PARENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens (user_id);
CREATE TABLE IF NOT EXISTS active_sessions (
    session_id TEXT PRIMARY KEY,
    candidate TEXT NOT NULL,
    session_json TEXT NOT NULL,
    feedback_json TEXT DEFAULT '[]',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_active_sessions_candidate ON active_sessions (candidate);
"""


def sqlite_conn() -> sqlite3.Connection:
    """Open the shared raw-sqlite connection (WAL, idempotent DDL)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(_PARENT_SCHEMA)
    return conn


def learner_db_url() -> str:
    """URL for the learner model's SQLAlchemy engine (one shared file)."""
    return os.environ.get("LEARNING_PARTNER_DB_URL") or f"sqlite:///{DB_PATH}"


class Base(DeclarativeBase):
    """Declarative base for all learner ORM models."""


def create_session_factory(url: Optional[str] = None):
    """Build a sessionmaker bound to the given URL (defaults to the shared file).

    Ensures the SQLite parent directory exists before connecting. Only
    SQLite-specific connection args are applied, guarded by the URL scheme.
    """
    url = url or learner_db_url()
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if url != "sqlite:///:memory:":
            db_path = Path(url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args=connect_args)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return session_factory, engine


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


def learner_engine():
    """SQLAlchemy engine for the learner model tables."""
    _, engine = create_session_factory(learner_db_url())
    return engine


def create_schema():
    """Create all learner tables (idempotent). Returns the engine."""
    # Imported lazily: the table models live in the learner topic modules,
    # which import Base/converters from this module at load time.
    from learner import (  # noqa: F401  (register tables)
        evidence,
        frontier,
        graph,
        misconception,
        states,
    )
    from coach import tasks as _tasks  # noqa: F401  (register task tables)

    engine = learner_engine()
    Base.metadata.create_all(engine)
    # Cleanup legacy tables from before assessment_* persistence removal.
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS assessment_targets")
        conn.exec_driver_sql("DROP TABLE IF EXISTS assessment_tasks")
    return engine


def learner_session() -> Session:
    """Open a short-lived ORM session bound to the shared file."""
    session_factory, _ = create_session_factory(learner_db_url())
    return session_factory()
