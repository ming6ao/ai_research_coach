"""Single database module for the whole app.

One SQLite file (``data/coach.db``) holds the raw-sqlite tables (``users``,
``auth_tokens``, ``active_sessions``, ``oauth_states``) and the SQLAlchemy tables (``tasks``,
``task_attempts``, ``user_skill_beliefs``). ``sqlite_conn()`` owns the
raw-sqlite DDL and is used by ``backend/auth.py`` and
``backend/dependencies.py``; ``Base`` / ``create_session_factory()`` own the
SQLAlchemy side. ``create_schema()`` drops removed columns/tables (skill tags,
knowledge-graph / learner tables) and collapses legacy per-skill beliefs to a
single overall-ability row per candidate so old databases converge.
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
    status TEXT NOT NULL DEFAULT 'active',
    resumed_from_share TEXT,
    fork_of TEXT,
    meta_json TEXT DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_active_sessions_candidate ON active_sessions (candidate);
CREATE TABLE IF NOT EXISTS trajectory_shares (
    id TEXT PRIMARY KEY,
    source_session_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_trajectory_shares_source ON trajectory_shares (source_session_id);
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oauth_states_expiry ON oauth_states (expires_at);
"""

# Tables from the removed knowledge-graph / learner model and legacy logs.
# Dropped on startup so databases created before the removal converge to the
# fresh design (no data is preserved — see the removal plan). ``task_attempts``
# is superseded by ``session_steps`` (RL-shaped per-step rows).
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
    "task_attempts",
)

# Columns from the removed per-task frozen graph, skill tags, hints, curated
# follow-ups, and thematic clusters. Best-effort DROP COLUMN; failures are
# swallowed so startup never breaks.
_DROPPED_TASK_COLUMNS = (
    "graph_json", "target_node_id", "target_node_slug", "expected_time_min",
    "skill", "hints_json", "cluster_id", "followups_json",
    # Retired version-chain columns (replaced by delivery='phased').
    "version_index", "depends_on_task_id", "version_root_id",
)

# Tables reset_database() wipes (activity/progress) vs. preserves (identity/auth
# and the task bank — the DB is the source of truth for tasks).
_WIPED_TABLES = ("session_steps", "user_skill_beliefs", "active_sessions", "trajectory_shares")
_PRESERVED_TABLES = ("users", "auth_tokens", "oauth_states", "tasks")


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


def _migrate_skill_beliefs_to_ability(conn) -> None:
    """Migrate legacy per-skill beliefs to the hierarchical (level, key) rows.

    Old DBs hold one ``user_skill_beliefs`` row per (candidate, skill).
    The fresh design stores one row per ``(candidate, level, key)``:

    - Rows whose legacy ``skill`` name matches a known family are kept as
      ``('family', <name>)``.
    - Remaining legacy per-skill rows collapse to one ``('global', 'overall')``
      row per candidate (keep the row with the most answered questions).
    - Rows without a legacy skill (already overall) become
      ``('global', 'overall')``.
    - Duplicate ``(candidate, level, key)`` rows collapse keeping the most
      answered, then a unique index is created (SQLite cannot add a UNIQUE
      constraint via ``ALTER TABLE``).

    Best-effort: failures are swallowed so startup never breaks.
    """
    try:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(user_skill_beliefs)").fetchall()]
    except Exception:
        return
    if not cols:
        return
    try:
        # Legacy per-skill belief rows are retired with the old taxonomy: any
        # legacy `skill` column is collapsed to the global row (the candidate's
        # overall ability). Per-node rows are rebuilt by live sessions under
        # the new (domain/area/skill) hierarchy.
        families: set[str] = set()

        if "level" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE user_skill_beliefs ADD COLUMN level TEXT DEFAULT 'global'"
            )
        if "key" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE user_skill_beliefs ADD COLUMN key TEXT DEFAULT 'overall'"
            )

        if "skill" in cols:
            # Partition rows by their legacy skill value.
            rows = conn.exec_driver_sql(
                "SELECT id, candidate, skill, questions_answered FROM user_skill_beliefs"
            ).fetchall()
            keep_ids: set[str] = set()
            per_candidate: dict[str, tuple[str, int]] = {}
            for row_id, candidate, skill, qa in rows:
                qa = qa or 0
                if skill and str(skill).strip() in families:
                    keep_ids.add(row_id)
                    conn.exec_driver_sql(
                        "UPDATE user_skill_beliefs SET level = 'family', key = ? WHERE id = ?",
                        (str(skill).strip(), row_id),
                    )
                else:
                    cur = per_candidate.get(candidate)
                    if cur is None or qa > cur[1]:
                        per_candidate[candidate] = (row_id, qa)
            for candidate, (keep_id, _qa) in per_candidate.items():
                conn.exec_driver_sql(
                    "UPDATE user_skill_beliefs SET level = 'global', key = 'overall' WHERE id = ?",
                    (keep_id,),
                )
                keep_ids.add(keep_id)
            # Delete every remaining junk row (keep global + family rows only).
            for (row_id,) in conn.exec_driver_sql("SELECT id FROM user_skill_beliefs").fetchall():
                if row_id not in keep_ids:
                    conn.exec_driver_sql(
                        "DELETE FROM user_skill_beliefs WHERE id = ?", (row_id,)
                    )
            try:
                conn.exec_driver_sql("ALTER TABLE user_skill_beliefs DROP COLUMN skill")
            except Exception:
                pass
        else:
            # No legacy skill column: normalize NULL/empty level/key values.
            conn.exec_driver_sql(
                "UPDATE user_skill_beliefs SET level = 'global' WHERE level IS NULL OR level = ''"
            )
            conn.exec_driver_sql(
                "UPDATE user_skill_beliefs SET key = 'overall' WHERE key IS NULL OR key = ''"
            )

        # Collapse any duplicate (candidate, level, key) rows (most answered wins).
        dup_rows = conn.exec_driver_sql(
            "SELECT candidate, level, key FROM user_skill_beliefs "
            "GROUP BY candidate, level, key HAVING COUNT(*) > 1"
        ).fetchall()
        for candidate, level, key in dup_rows:
            best = conn.exec_driver_sql(
                "SELECT id FROM user_skill_beliefs WHERE candidate = ? AND level = ? AND key = ? "
                "ORDER BY questions_answered DESC, updated_at DESC LIMIT 1",
                (candidate, level, key),
            ).fetchone()
            if best:
                conn.exec_driver_sql(
                    "DELETE FROM user_skill_beliefs WHERE candidate = ? AND level = ? AND key = ? AND id != ?",
                    (candidate, level, key, best[0]),
                )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_skill_beliefs "
            "ON user_skill_beliefs (candidate, level, key)"
        )
    except Exception:
        pass


def create_schema():
    """Create all tables (idempotent) and drop removed ones. Returns engine."""
    from coach import tasks as _tasks  # noqa: F401  (register task tables)
    from coach import steps as _steps  # noqa: F401  (register session_steps)

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
            conn.exec_driver_sql("DROP INDEX IF EXISTS ix_tasks_skill")
        except Exception:
            pass
        _migrate_skill_beliefs_to_ability(conn)
        _migrate_active_sessions(conn)
        try:
            cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(tasks)").fetchall()]
            if "context_notes" not in cols:
                conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN context_notes TEXT DEFAULT ''")
            if "target_text" not in cols:
                conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN target_text TEXT")
            if "tags_json" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE tasks ADD COLUMN tags_json TEXT DEFAULT "
                    "'{\"primary\": null, \"secondary\": []}'"
                )
            if "task_type" not in cols:
                conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT 'implement'")
            if "language" not in cols:
                conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN language TEXT DEFAULT 'python'")
            if "parts_json" not in cols:
                conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN parts_json TEXT DEFAULT '[]'")
            if "delivery" not in cols:
                conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN delivery TEXT DEFAULT 'block'")
        except Exception:
            pass
    with _schema_lock:
        _schema_done.add(key)
    # Backfill session_steps from legacy JSON blobs (deterministic replay) so
    # old sessions become exportable episodes. Best-effort.
    try:
        from coach.steps import backfill_session_steps

        backfill_session_steps()
    except Exception:
        pass
    return engine


def _migrate_active_sessions(conn) -> None:
    """Add episode-header columns to ``active_sessions`` and drop ``feedback_json``.

    ``session_json`` keeps its name but its content becomes a compact live
    state; per-step data moves to ``session_steps``. Best-effort so startup
    never breaks.
    """
    try:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(active_sessions)").fetchall()]
    except Exception:
        return
    for col, ddl in (
        ("status", "ALTER TABLE active_sessions ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"),
        ("resumed_from_share", "ALTER TABLE active_sessions ADD COLUMN resumed_from_share TEXT"),
        ("fork_of", "ALTER TABLE active_sessions ADD COLUMN fork_of TEXT"),
        ("meta_json", "ALTER TABLE active_sessions ADD COLUMN meta_json TEXT DEFAULT '{}'"),
    ):
        if col not in cols:
            try:
                conn.exec_driver_sql(ddl)
            except Exception:
                pass
    if "feedback_json" in cols:
        # Only drop the legacy column once every session has been backfilled
        # into session_steps (or has no legacy results to migrate); otherwise
        # the backfill would lose the per-step records.
        try:
            remaining = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM active_sessions "
                "WHERE feedback_json != '[]' OR session_json LIKE '%\"results\"%'"
            ).fetchone()[0]
        except Exception:
            remaining = 1
        if not remaining:
            try:
                conn.exec_driver_sql("ALTER TABLE active_sessions DROP COLUMN feedback_json")
            except Exception:
                pass


def learner_session() -> Session:
    """Open a short-lived ORM session bound to the shared file."""
    session_factory, _ = create_session_factory(learner_db_url())
    return session_factory()


def reset_database(preview: bool = False, wipe_tasks: bool = False) -> dict:
    """Wipe activity/progress data; optionally wipe the task bank too.

    Deletes every row from the activity tables (``session_steps``,
    ``user_skill_beliefs``, ``active_sessions``, ``trajectory_shares``).
    Identity/auth tables (``users``, ``auth_tokens``, ``oauth_states``) are
    always preserved. ``tasks`` is preserved by default (the DB is the source
    of truth for questions); pass ``wipe_tasks=True`` to also delete the entire
    task bank (used when re-authoring against a new taxonomy).

    ``preview=True`` returns per-table row counts without mutating anything;
    ``preview=False`` deletes the rows and returns what was removed.
    """
    create_schema()
    tables = list(_WIPED_TABLES) + (["tasks"] if wipe_tasks else [])
    preserved = [t for t in _PRESERVED_TABLES if not (wipe_tasks and t == "tasks")]
    with sqlite_conn() as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }
        if preview:
            return {
                "preview": True,
                "wipe_tasks": wipe_tasks,
                "wiped": counts,
                "total_deleted": sum(counts.values()),
                "preserved": preserved,
            }
        deleted: dict[str, int] = {}
        for table in tables:
            cur = conn.execute(f"DELETE FROM {table}")
            deleted[table] = cur.rowcount or 0
        conn.commit()

    return {
        "preview": False,
        "wipe_tasks": wipe_tasks,
        "wiped": deleted,
        "total_deleted": sum(deleted.values()),
        "preserved": preserved,
    }
