"""Session state management for the FastAPI backend.

Stores active sessions in SQLite so users can resume after page refresh. A
newly started session is only staged in memory; it is written to the database
when the first answer is scored, so abandoned sessions are never stored.
Also resolves a candidate identity: a signed-in user is keyed by email; a
guest is keyed by a stable per-browser ``X-Guest-Id`` header (when present)
so anonymous mastery carries across sessions in the same browser.
"""

import json
import re
import sqlite3
import threading
import time
import uuid
from collections import OrderedDict
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
    """SQLite-backed session state store with deferred persistence.

    ``active_sessions`` is the episode header: ``session_json`` holds a compact
    live state (tasks, index, asked ids, ability) — the trajectory itself lives
    in ``session_steps`` (see ``coach.steps``).

    A newly started session is only *staged* in a process-local buffer; it is
    written to ``active_sessions`` the first time an answer is scored
    (``save(..., persist=True)``). An abandoned "Start practice" click is
    therefore never stored and never shows up in Recent sessions. The buffer
    is bounded by TTL + size; a process restart drops only unanswered drafts
    (no answer is ever lost).
    """

    # Draft sessions older than this (or beyond the size cap) are discarded.
    _PENDING_TTL_SECONDS = 2 * 60 * 60
    _PENDING_MAX = 500

    def __init__(self) -> None:
        self._pending: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._pending_lock = threading.Lock()

    # -- pending (un-answered) drafts ------------------------------------

    def _prune_pending(self) -> None:
        """Drop expired drafts and enforce the size cap (caller holds lock)."""
        now = time.monotonic()
        for sid in [
            sid
            for sid, entry in self._pending.items()
            if now - entry["created_at"] > self._PENDING_TTL_SECONDS
        ]:
            self._pending.pop(sid, None)
        while len(self._pending) > self._PENDING_MAX:
            self._pending.popitem(last=False)

    def create(
        self,
        candidate: str,
        *,
        meta_json: dict | None = None,
    ) -> str:
        """Stage a new session id; nothing is written to the database yet."""
        sid = uuid.uuid4().hex[:12]
        with self._pending_lock:
            self._prune_pending()
            self._pending[sid] = {
                "candidate": candidate,
                "state": {},
                "meta_json": dict(meta_json or {}),
                "status": "active",
                "created_at": time.monotonic(),
            }
        return sid

    def is_persisted(self, session_id: str) -> bool:
        """True once the session has a row in ``active_sessions``."""
        with self._pending_lock:
            if session_id in self._pending:
                return False
        with _connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM active_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row is not None

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._pending_lock:
            self._prune_pending()
            entry = self._pending.get(session_id)
            if entry is not None:
                state = dict(entry.get("state") or {})
                state["_status"] = entry.get("status", "active")
                state["_pending"] = True
                return state
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

    def save(
        self,
        session_id: str,
        state: Dict[str, Any],
        feedback_list: List[Dict] = None,
        *,
        persist: bool = False,
        title: Optional[str] = None,
        summary: Optional[str] = None,
    ):
        """Persist the compact session state (steps are stored separately).

        While the session is still a draft (``persist=False``) the state is
        held in memory. Passing ``persist=True`` (the first scored answer)
        promotes it to ``active_sessions`` via an upsert; ``title``/``summary``
        are written on that first insert and preserved on later saves.
        ``feedback_list`` is accepted for backward compatibility and ignored —
        review records now live in ``session_steps``.
        """
        if not persist:
            with self._pending_lock:
                entry = self._pending.get(session_id)
                if entry is not None:
                    entry["state"] = state
                    return

        now = _utcnow()
        candidate = ""
        session_blob = state.get("session") if isinstance(state, dict) else None
        if isinstance(session_blob, dict):
            candidate = session_blob.get("candidate") or ""
        with self._pending_lock:
            entry = self._pending.pop(session_id, None)
        if entry is not None:
            candidate = candidate or entry.get("candidate") or ""
            meta = entry.get("meta_json") or {}
        else:
            meta = {}
        with _connect() as conn:
            conn.execute(
                "INSERT INTO active_sessions "
                "(session_id, candidate, session_json, status, meta_json, title, summary, updated_at) "
                "VALUES (?, ?, ?, 'active', ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "session_json = excluded.session_json, updated_at = excluded.updated_at, "
                "title = COALESCE(NULLIF(excluded.title, ''), active_sessions.title), "
                "summary = COALESCE(NULLIF(excluded.summary, ''), active_sessions.summary)",
                (
                    session_id,
                    candidate,
                    json.dumps(state),
                    json.dumps(meta),
                    title or "",
                    summary or "",
                    now,
                ),
            )

    def set_status(self, session_id: str, status: str) -> None:
        with self._pending_lock:
            entry = self._pending.get(session_id)
            if entry is not None:
                entry["status"] = status
                return
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
        with self._pending_lock:
            self._pending.pop(session_id, None)
        with _connect() as conn:
            conn.execute("DELETE FROM active_sessions WHERE session_id = ?", (session_id,))

    def list_by_candidate(self, candidate: str) -> List[Dict[str, Any]]:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT session_id, candidate, title, summary, updated_at "
                "FROM active_sessions WHERE candidate = ? ORDER BY updated_at DESC",
                (candidate,),
            ).fetchall()
        return [
            {
                "session_id": r[0],
                "candidate": r[1],
                "title": r[2] or "",
                "summary": r[3] or "",
                "updated_at": r[4],
            }
            for r in rows
        ]


_store = SessionState()


def get_store() -> SessionState:
    return _store
