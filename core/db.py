"""Single database module for the whole app.

One SQLite file (``data/coach.db``) holds both the parent's small raw-sqlite
tables (``users``, ``auth_tokens``, ``active_sessions``) and the learner
model's SQLAlchemy tables. ``sqlite_conn()`` owns the parent DDL and is used by
``backend/auth.py`` and ``backend/dependencies.py``; ``create_schema()`` /
``learner_engine()`` own the SQLAlchemy schema (12 tables).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

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
    """Open the shared parent-schema connection (WAL, idempotent DDL)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(_PARENT_SCHEMA)
    return conn


def learner_db_url() -> str:
    """URL for the learner model's SQLAlchemy engine (one shared file)."""
    return os.environ.get("LEARNING_PARTNER_DB_URL") or f"sqlite:///{DB_PATH}"


def learner_engine():
    """SQLAlchemy engine for the learner model tables."""
    from core.learner.storage.database import create_session_factory

    _, engine = create_session_factory(learner_db_url())
    return engine


def create_schema():
    """Create all learner tables (idempotent). Returns the engine."""
    from core.learner.storage import models  # noqa: F401  (register tables)
    from core.learner.storage.database import Base

    engine = learner_engine()
    Base.metadata.create_all(engine)
    return engine


def learner_session():
    """Open a short-lived ORM session bound to the shared file."""
    from core.learner.storage.database import create_session_factory

    session_factory, _ = create_session_factory(learner_db_url())
    return session_factory()