"""Session state management for the FastAPI backend.

Persists active sessions to SQLite so users can resume after page refresh.
"""

import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from coach.db import sqlite_conn


def _connect() -> sqlite3.Connection:
    return sqlite_conn()


from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionState:
    """SQLite-backed session state store."""

    def create(self, candidate: str) -> str:
        sid = uuid.uuid4().hex[:12]
        now = _utcnow()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO active_sessions (session_id, candidate, session_json, feedback_json, updated_at) VALUES (?, ?, ?, ?, ?)",
                (sid, candidate, "{}", "[]", now),
            )
        return sid

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with _connect() as conn:
            row = conn.execute(
                "SELECT session_json, feedback_json FROM active_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        state = json.loads(row[0])
        state["_feedback_list"] = json.loads(row[1])
        return state

    def save(self, session_id: str, state: Dict[str, Any], feedback_list: List[Dict] = None):
        now = _utcnow()
        with _connect() as conn:
            conn.execute(
                "UPDATE active_sessions SET session_json = ?, feedback_json = ?, updated_at = ? WHERE session_id = ?",
                (json.dumps(state), json.dumps(feedback_list or []), now, session_id),
            )

    def delete(self, session_id: str):
        with _connect() as conn:
            conn.execute("DELETE FROM active_sessions WHERE session_id = ?", (session_id,))

    def list_by_candidate(self, candidate: str) -> List[Dict[str, Any]]:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT session_id, candidate, updated_at FROM active_sessions WHERE candidate = ? ORDER BY updated_at DESC",
                (candidate,),
            ).fetchall()
        return [
            {"session_id": r[0], "candidate": r[1], "updated_at": r[2]}
            for r in rows
        ]


_store = SessionState()


def get_store() -> SessionState:
    return _store
