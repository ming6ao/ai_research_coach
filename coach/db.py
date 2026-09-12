"""Single database module for the whole app.

One SQLite file (``data/coach.db``) holds the raw-sqlite tables (``users``,
``auth_tokens``, ``active_sessions``) and the SQLAlchemy tables (``tasks``,
``task_attempts``, ``user_skill_beliefs``). ``sqlite_conn()`` owns the
raw-sqlite DDL and is used by ``backend/auth.py`` and
``backend/dependencies.py``; ``Base`` / ``create_session_factory()`` own the
SQLAlchemy side. ``create_schema()`` drops the removed knowledge-graph /
learner tables so old databases converge to the fresh 6-table design.
"""

from __future__ import annotations

import os
import sqlite3
import threading
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

# Tables from the removed knowledge-graph / learner model. Dropped on
# startup so databases created before the removal converge to the fresh
# design (no data is preserved — see the removal plan).
_DROPPED_TABLES = (
    "knowledge_nodes",
    "knowledge_edges",
    "learners",
    "learner_knowledge_states",
    "evidence",
    "learner_misconceptions",
    "learner_frontier",
    "assessment_targets",
    "assessment_tasks",
)

# Columns from the removed per-task frozen graph. Best-effort DROP COLUMN;
# failures are swallowed so startup never breaks.
_DROPPED_TASK_COLUMNS = ("graph_json", "target_node_id", "target_node_slug", "expected_time_min")


# Process-local guard so per-request create_schema()/sqlite_conn() calls only
# run DDL/migrations once per DB file. Keyed by path/URL so tests that
# monkeypatch DB_PATH to a temp file still get fresh DDL. Call sites are
# unchanged — repeat calls become cheap no-ops.
_schema_done: set[str] = set()
_schema_lock = threading.Lock()


def sqlite_conn() -> sqlite3.Connection:
    """Open the shared raw-sqlite connection (WAL, idempotent DDL)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    key = f"raw:{DB_PATH}"
    with _schema_lock:
        done = key in _schema_done
    if not done:
        conn.executescript(_PARENT_SCHEMA)
        with _schema_lock:
            _schema_done.add(key)
    return conn


def learner_db_url() -> str:
    """URL for the SQLAlchemy engine (one shared file)."""
    return os.environ.get("LEARNING_PARTNER_DB_URL") or f"sqlite:///{DB_PATH}"


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


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
    """SQLAlchemy engine for the app tables."""
    _, engine = create_session_factory(learner_db_url())
    return engine


def create_schema():
    """Create all tables (idempotent) and drop removed ones. Returns engine."""
    from coach import tasks as _tasks  # noqa: F401  (register task tables)

    url = learner_db_url()
    key = f"orm:{url}"
    with _schema_lock:
        if key in _schema_done:
            return learner_engine()
    engine = learner_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table in _DROPPED_TABLES:
            try:
                conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
            except Exception:
                pass
        try:
            cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(tasks)").fetchall()]
        except Exception:
            cols = []
        for col in _DROPPED_TASK_COLUMNS:
            if col in cols:
                try:
                    conn.exec_driver_sql(f"ALTER TABLE tasks DROP COLUMN {col}")
                except Exception:
                    pass
        try:
            cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(tasks)").fetchall()]
            if "context_notes" not in cols:
                conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN context_notes TEXT DEFAULT ''")
            if "target_text" not in cols:
                conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN target_text TEXT")
        except Exception:
            pass
    with _schema_lock:
        _schema_done.add(key)
    return engine


def learner_session() -> Session:
    """Open a short-lived ORM session bound to the shared file."""
    session_factory, _ = create_session_factory(learner_db_url())
    return session_factory()
