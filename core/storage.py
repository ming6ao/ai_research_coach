import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "coach.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    candidate TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    overall_score REAL,
    verdict TEXT,
    report_json TEXT,
    session_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_assessments_candidate ON assessments (candidate);
CREATE TABLE IF NOT EXISTS learner_bindings (
    candidate TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA)
    return conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_assessment(session, report: dict) -> str:
    """Persist a finished assessment (session + report). Returns the assessment id."""
    import uuid

    aid = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO assessments
              (id, candidate, finished_at, overall_score, verdict, report_json, session_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aid,
                session.candidate,
                _utcnow(),
                report.get("overall_score"),
                report.get("verdict"),
                json.dumps(report),
                json.dumps(session.to_dict()),
            ),
        )
    return aid


def get_assessment(assessment_id: str) -> dict:
    """Return full assessment data including session state."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT report_json, session_json FROM assessments WHERE id = ?",
            (assessment_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "report": json.loads(row[0]) if row[0] else None,
        "session": json.loads(row[1]) if row[1] else None,
    }


def list_assessments(limit: int = 50) -> list:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, candidate, finished_at, overall_score, verdict
            FROM assessments
            ORDER BY finished_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": r[0],
            "candidate": r[1],
            "finished_at": r[2],
            "overall_score": r[3],
            "verdict": r[4],
        }
        for r in rows
    ]


def list_assessments_by_candidate(candidate: str) -> list:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, candidate, finished_at, overall_score, verdict
            FROM assessments
            WHERE candidate = ?
            ORDER BY finished_at DESC
            """,
            (candidate,),
        ).fetchall()
    return [
        {
            "id": r[0],
            "candidate": r[1],
            "finished_at": r[2],
            "overall_score": r[3],
            "verdict": r[4],
        }
        for r in rows
    ]


def delete_assessment(assessment_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM assessments WHERE id = ?", (assessment_id,)
        )
    return cur.rowcount > 0


def delete_assessments_by_candidate(candidate: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM assessments WHERE candidate = ?", (candidate,)
        )
    return cur.rowcount


def clear_all():
    """Delete all data from both tables."""
    with _connect() as conn:
        conn.execute("DELETE FROM active_sessions")
        conn.execute("DELETE FROM assessments")


def get_learner_binding(candidate: str) -> str | None:
    """Return the MVP learner id bound to a candidate, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT learner_id FROM learner_bindings WHERE candidate = ?",
            (candidate,),
        ).fetchone()
    return row[0] if row else None


def set_learner_binding(candidate: str, learner_id: str) -> None:
    """Idempotently bind a candidate to an MVP learner id."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO learner_bindings (candidate, learner_id, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(candidate) DO UPDATE SET learner_id = excluded.learner_id
            """,
            (candidate, learner_id, _utcnow()),
        )


def delete_learner_binding(candidate: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM learner_bindings WHERE candidate = ?", (candidate,)
        )
