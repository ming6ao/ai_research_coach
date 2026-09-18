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
    """SQLite-backed session state store.

    ``active_sessions`` is the episode header: ``session_json`` holds a compact
    live state (tasks, index, asked ids, ability) — the trajectory
    itself lives in ``session_steps`` (see ``coach.steps``). ``feedback_json``
    no longer exists; review records are derived from steps.
    """

    def create(
        self,
        candidate: str,
        *,
        meta_json: dict | None = None,
    ) -> str:
        sid = uuid.uuid4().hex[:12]
        now = _utcnow()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO active_sessions "
                "(session_id, candidate, session_json, status, meta_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    sid,
                    candidate,
                    "{}",
                    "active",
                    json.dumps(meta_json or {}),
                    now,
                ),
            )
        return sid

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with _connect() as conn:
            row = conn.execute(
                "SELECT session_json, status FROM active_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        session_json, status = row
        try:
            state = json.loads(session_json or "{}")
        except Exception:
            state = {}
        if not isinstance(state, dict):
            state = {}
        state["_status"] = status
        return state

    def save(self, session_id: str, state: Dict[str, Any], feedback_list: List[Dict] = None):
        """Persist the compact session state (steps are stored separately).

        ``feedback_list`` is accepted for backward compatibility and ignored —
        review records now live in ``session_steps``.
        """
        now = _utcnow()
        with _connect() as conn:
            conn.execute(
                "UPDATE active_sessions SET session_json = ?, updated_at = ? WHERE session_id = ?",
                (json.dumps(state), now, session_id),
            )

    def set_status(self, session_id: str, status: str) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE active_sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                (status, _utcnow(), session_id),
            )

    def delete(self, session_id: str):
        from coach.explanations import delete_session_explanations
        from coach.steps import delete_session_data

        delete_session_data(session_id)
        delete_session_explanations(session_id)
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
