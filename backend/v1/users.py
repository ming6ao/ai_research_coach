"""v1 user resources: identity, own sessions, progress overview, data wipe.

- GET    /api/v1/me           -> {data: user} (requires auth)
- GET    /api/v1/me/sessions  -> {data: [{id, candidate, done, updated_at}], meta}
- GET    /api/v1/me/overview  -> {data: {ability, mastery, sessions}} (guests ok)
- DELETE /api/v1/me/data      -> {data: {deleted, deleted_by_table}} (guests ok)

Guest requests resolve to a stable per-browser candidate via the
``X-Guest-Id`` header (see :func:`backend.dependencies.resolve_candidate`).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request

from backend.auth import get_current_user, require_user
from backend.dependencies import get_store, resolve_candidate
from backend.v1.pagination import PageParams, paginate

router = APIRouter(tags=["v1:users"])


@router.get("/me", summary="Current user")
def get_me(user: dict = Depends(require_user)):
    return {"data": user}


@router.get("/me/tasks", summary="List my own tasks")
def list_my_tasks(
    q: Optional[str] = None,
    page: PageParams = Depends(),
    user: dict = Depends(require_user),
):
    """Tasks owned by the current user (curator UI), with attempt counts."""
    from coach.tasks import list_tasks_for_owner

    rows = list_tasks_for_owner(user["email"], q=q or None, limit=500)
    items, meta = paginate(rows, page.page, page.page_size)
    return {"data": items, "meta": meta}


def _progress_for_candidate(candidate: str) -> tuple[Optional[dict], Optional[dict]]:
    """Persisted (ability, mastery) snapshot for a candidate, or (None, None).

    Built directly from ``user_skill_beliefs`` rows so the home page can show
    cross-session progress without a live session. Mastery folds per-node
    statistics with read-time shrinkage exactly like ``_mastery_dict``.
    """
    from coach.area_score import AreaState, area_report_dict
    from coach.tasks import get_area_beliefs, get_skill_belief
    from coach.taxonomy import NODE_LEVEL

    global_b = get_skill_belief(candidate)
    if global_b is None:
        return None, None
    global_state = AreaState(
        mean=global_b["mean"],
        variance=global_b["variance"],
        questions_answered=global_b["questions_answered"],
    )
    node_states: dict = {}
    for (level, key), b in get_area_beliefs(candidate).items():
        if NODE_LEVEL.get(key) is None:
            continue  # legacy/retired node
        node_states[key] = AreaState(
            mean=b["mean"], variance=b["variance"], questions_answered=b["questions_answered"]
        )
    mastery = area_report_dict(global_state, node_states)
    from coach.score import confidence_from_variance

    ability = {
        "score": global_b["mean"],
        "confidence": confidence_from_variance(global_state.variance),
        "questions_answered": global_b["questions_answered"],
    }
    return ability, mastery


def _task_counts(candidate: str) -> dict[str, int]:
    """Visible bank task counts keyed by taxonomy node (skill/area/domain).

    Each task is counted once against its **primary** tag and all of that
    tag's ancestors. Secondary tags are deliberately ignored: a node is only
    surfaced on the home page when the picker can actually serve a task for it
    (``coach/picker.py`` matches the task-level primary tag), so a
    secondary-only node must not appear or clicking it would fall through to
    generated content. Generated session artifacts are excluded by
    ``list_visible_tasks``.
    """
    from coach.tasks import list_visible_tasks
    from coach.taxonomy import ancestors, resolve_node

    counts: dict[str, int] = {}
    for task in list_visible_tasks(candidate):
        primary = (task.get("tags") or {}).get("primary")
        canon = resolve_node(primary)
        if canon is None:
            continue
        for node in {canon, *ancestors(canon)}:
            counts[node] = counts.get(node, 0) + 1
    return counts


def _session_rows(candidate: str) -> list[dict]:
    """Recent sessions for the home page.

    ``done`` is read from the persisted session status, set when the learner
    explicitly finishes (``POST /sessions/{id}/completion``). It must never be
    derived by running the picker: ``pick_next_task`` can mint an LLM
    challenge, which would make loading the home page slow and would generate
    tasks as a side effect of a read request.
    """
    store = get_store()
    rows = []
    for s in store.list_by_candidate(candidate):
        state = store.get(s["session_id"])
        done = bool(state and state.get("_status") == "done")
        rows.append({
            "id": s["session_id"],
            "candidate": s["candidate"],
            "title": s.get("title") or "",
            "summary": s.get("summary") or "",
            "done": done,
            "updated_at": s["updated_at"],
        })
    rows.sort(key=lambda s: s["updated_at"], reverse=True)
    return rows


@router.get("/me/sessions", summary="List my sessions")
def list_my_sessions(
    page: PageParams = Depends(), user: Optional[dict] = Depends(get_current_user), request: Request = None
):
    candidate = resolve_candidate(user, request)
    items, meta = paginate(_session_rows(candidate), page.page, page.page_size)
    return {"data": items, "meta": meta}


@router.get("/me/overview", summary="Cross-session progress overview")
def my_overview(user: Optional[dict] = Depends(get_current_user), request: Request = None):
    """Ability + mastery + recent sessions for the merged home page.

    Works for guests too (stable per-browser identity) so anonymous learners
    see persistent progress across sessions.
    """
    candidate = resolve_candidate(user, request)
    ability, mastery = _progress_for_candidate(candidate)
    sessions = _session_rows(candidate)[:20]
    return {
        "data": {
            "candidate": candidate,
            "ability": ability,
            "mastery": mastery,
            "task_counts": _task_counts(candidate),
            "sessions": sessions,
        }
    }


@router.delete("/me/data", summary="Delete all my data")
def delete_my_data(user: Optional[dict] = Depends(get_current_user), request: Request = None):
    from coach.admin import clear_candidate_everything

    candidate = resolve_candidate(user, request)
    # Self-service wipe: keep authored questions, drop progress and generated
    # session artifacts.
    result = clear_candidate_everything(candidate, keep_authored_tasks=True)
    return {
        "data": {
            "deleted": result["deleted"]["total"],
            "deleted_by_table": result["deleted"],
        }
    }