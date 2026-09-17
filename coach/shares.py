"""Trajectory shares: frozen, identity-stripped episode prefixes + helpers.

A share is a point-in-time, resumable checkpoint of an episode (see
``docs/collaboration-design.md``). It stores an opaque token, the resume
boundary, and a frozen snapshot (compact session state + the prefix step rows,
answers stripped). Resuming clones nothing until the first write (Copy-on-Write).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from coach.db import sqlite_conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_snapshot(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed


def create_share(
    source_session_id: str,
    step_index: int,
    snapshot: dict,
    created_by: str,
) -> str:
    """Store a share and return its opaque token."""
    token = uuid.uuid4().hex
    with sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO trajectory_shares "
            "(id, source_session_id, step_index, snapshot_json, created_by, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                source_session_id,
                int(step_index or 0),
                json.dumps(snapshot),
                created_by,
                _utcnow(),
                None,
            ),
        )
    return token


def get_share(token: str) -> dict | None:
    """Return a share dict (with parsed snapshot) or None."""
    with sqlite_conn() as conn:
        row = conn.execute(
            "SELECT id, source_session_id, step_index, snapshot_json, created_by, created_at "
            "FROM trajectory_shares WHERE id = ?",
            (token,),
        ).fetchone()
    if row is None:
        return None
    return {
        "token": row[0],
        "source_session_id": row[1],
        "step_index": row[2],
        "snapshot": _parse_snapshot(row[3]),
        "created_by": row[4],
        "created_at": row[5],
    }


def delete_share(token: str) -> int:
    with sqlite_conn() as conn:
        cur = conn.execute("DELETE FROM trajectory_shares WHERE id = ?", (token,))
        conn.commit()
        return cur.rowcount or 0


def delete_shares_for_source(source_session_id: str) -> int:
    with sqlite_conn() as conn:
        cur = conn.execute(
            "DELETE FROM trajectory_shares WHERE source_session_id = ?",
            (source_session_id,),
        )
        conn.commit()
        return cur.rowcount or 0


def effective_steps(session_id: str, state: dict) -> list[dict]:
    """Steps of a session: the share's prefix while unreforged, else rows.

    A resumed (Copy-on-Write) session has no ``session_steps`` rows until its
    first write; until then its history is served from the share snapshot.
    """
    token = state.get("_resumed_from_share")
    if token:
        share = get_share(token)
        if share is not None:
            return share["snapshot"].get("steps", [])
    from coach.steps import list_steps

    return list_steps(session_id)


def build_share_snapshot(session, steps: list[dict]) -> dict:
    """Frozen snapshot: compact session state + prefix steps (answers stripped).

    ``candidate`` stays in the internal snapshot (needed for materialization)
    but is never exposed over the share API; code answers are stripped so no
    user content is shared.
    """
    stripped = [{**st, "user_answer": ""} for st in steps]
    return {"session": session.to_dict(), "steps": stripped}


def feedback_from_steps(steps: list[dict]) -> list[dict]:
    """Render step rows as the review ``results`` records the frontend expects.

    Mirrors the legacy ``feedback_json`` entry shape.
    """
    out = []
    for st in steps:
        task = st.get("task_snapshot") or {}
        coaching = st.get("coaching") or {}
        parts = task.get("parts")
        phase_index = None
        phase_total = None
        if (task.get("delivery") or "block") == "phased" and parts:
            phase_total = len(parts)
            result_parts = (st.get("result") or {}).get("parts") or []
            key = result_parts[0].get("key") if result_parts else None
            keys = [p.get("key") for p in parts]
            if key in keys:
                phase_index = keys.index(key) + 1
                parts = [parts[phase_index - 1]]
        out.append(
            {
                "task_id": st.get("task_id") or task.get("id"),
                "prompt": task.get("prompt", ""),
                "type": "code",
                "user_answer": st.get("user_answer") or "",
                "result": st.get("result") or {},
                "feedback": coaching.get("feedback", ""),
                "coach": coaching,
                "hints_used": st.get("hints_used") or [],
                "tags": task.get("tags"),
                "parts": parts,
                "language": task.get("language") or "python",
                "scored": True,
                "delivery": task.get("delivery") or "block",
                "phase_index": phase_index,
                "phase_total": phase_total,
            }
        )
    return out