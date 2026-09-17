"""v1 shared-trajectory resources: open a share, resume it (Copy-on-Write),
revoke it.

Shapes (all wrapped in ``{"data": ...}``):
- GET    /api/v1/shared/{token}             -> {token, step_index, steps:[...]}
- POST   /api/v1/shared/{token}/resume      -> {id, candidate, total_tasks, task_index, current_task, results, ability}
- DELETE /api/v1/shared/{token}             -> 204

No user information is shared: the payload contains task snapshots, scores,
and coaching only — never a candidate identity and never the sharer's code.
Resuming creates a brand-new episode owned by the resumer (resolved via
``resolve_candidate``); nothing is cloned until the first write.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.auth import get_current_user
from backend.dependencies import get_store, resolve_candidate
from coach.shares import delete_share, feedback_from_steps, get_share

router = APIRouter(prefix="/shared", tags=["v1:shares"])


def _load_share(token: str):
    share = get_share(token)
    if share is None:
        raise HTTPException(status_code=404, detail="Share not found.")
    return share


@router.get("/{token}", summary="Open a shared trajectory (review)")
def open_share(token: str, user: Optional[dict] = Depends(get_current_user)):
    share = _load_share(token)
    snapshot = share["snapshot"]
    steps = snapshot.get("steps", [])
    # Only the prefix boundary + review records are exposed (identity + answers
    # are stripped from the snapshot at creation).
    return {
        "data": {
            "token": share["token"],
            "step_index": share["step_index"],
            "steps": feedback_from_steps(steps),
        }
    }


@router.post("/{token}/resume", summary="Resume a shared trajectory as a new session")
def resume_share(
    token: str,
    user: Optional[dict] = Depends(get_current_user),
    request: Request = None,
):
    from coach.selection import pick_next_task
    from coach.session import Session
    from coach.tasks import get_skill_belief

    share = _load_share(token)
    candidate = resolve_candidate(user, request)
    snapshot = share["snapshot"]
    s = snapshot.get("session", {})

    # B's own persistent beliefs drive the continuation (per-user; never A's).
    ability = None
    try:
        b = get_skill_belief(candidate)
        if b:
            ability = {
                "score": b["mean"],
                "variance": b["variance"],
                "questions_answered": b["questions_answered"],
                "evidence": [],
            }
    except Exception:
        ability = None

    session_dict = {
        "candidate": candidate,
        "tasks": s.get("tasks", []),
        "index": s.get("index", len(snapshot.get("steps", []))),
        "ability": ability,
        "asked_task_ids": s.get("asked_task_ids", []),
        "generated_task_ids": s.get("generated_task_ids", []),
        "task_progress": s.get("task_progress", {}),
        "phase_attempts": s.get("phase_attempts", {}),
        "submission_index": s.get("submission_index", 0),
    }
    session = Session.from_dict(session_dict)

    store = get_store()
    session_id = store.create(
        candidate,
        resumed_from_share=token,
        fork_of=share["source_session_id"],
    )
    store.save(session_id, {"session": session.to_dict()})

    try:
        task = pick_next_task(candidate, session, session_id=session_id)
    except Exception:
        task = None

    # Prefix renders as read-only history (answers are stripped).
    feedback = feedback_from_steps(snapshot.get("steps", []))
    from backend.v1.sessions import _session_view

    return {
        "data": _session_view(
            session_id, session, task, feedback
        ),
    }


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a share")
def revoke_share(
    token: str,
    user: Optional[dict] = Depends(get_current_user),
    request: Request = None,
):
    share = _load_share(token)
    candidate = resolve_candidate(user, request)
    if share["created_by"] != candidate:
        raise HTTPException(status_code=403, detail="Only the sharer can revoke this share.")
    delete_share(token)
    return None