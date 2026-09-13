"""Session state management for the FastAPI backend.

Persists active sessions to SQLite so users can resume after page refresh.
Also resolves a candidate identity: a signed-in user is keyed by email; a
guest is keyed by a stable per-browser ``X-Guest-Id`` header (when present)
so anonymous mastery carries across sessions in the same browser.
"""

import json
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from coach.db import sqlite_conn


def _connect() -> sqlite3.Connection:
    return sqlite_conn()


from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# Guest ids from the browser are client-supplied; keep them to safe characters.
_GUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def resolve_candidate(user: Optional[dict], request) -> str:
    """Stable learner identity: signed-in email or a per-browser guest id.

    Guests send an ``X-Guest-Id`` header (generated once and kept in
    ``localStorage`` by the frontend) so their mastery and session history
    persist across sessions/reloads in the same browser. A missing or
    malformed header falls back to a fresh ephemeral guest id.
    """
    if user is not None:
        return user["email"]
    guest_id = (request.headers.get("X-Guest-Id") or "").strip()
    if _GUEST_ID_RE.match(guest_id):
        return f"guest-{guest_id}"
    return f"guest-{uuid.uuid4().hex[:8]}"


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
