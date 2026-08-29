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
    role TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    overall_score REAL,
    verdict TEXT,
    report_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_assessments_candidate ON assessments (candidate);
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
              (id, candidate, role, finished_at, overall_score, verdict, report_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aid,
                session.candidate,
                session.role,
                _utcnow(),
                report.get("overall_score"),
                report.get("verdict"),
                json.dumps(report),
            ),
        )
    return aid


def list_assessments(limit: int = 50) -> list:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, candidate, role, finished_at, overall_score, verdict
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
            "role": r[2],
            "finished_at": r[3],
            "overall_score": r[4],
            "verdict": r[5],
        }
        for r in rows
    ]