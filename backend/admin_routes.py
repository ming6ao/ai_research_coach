"""Admin/debug API routes (graph-free).

Tasks carry plain-English ``context_notes``; there are no knowledge graphs,
nodes, edges, or learner-model rows. Remaining endpoints cover candidate
management, question management, skill states, and DB stats.
"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from backend.auth import get_current_user, is_admin
from backend.dependencies import get_store

admin_router = APIRouter(prefix="/admin", tags=["admin"])


class TaskContextUpdate(BaseModel):
    context_notes: str = Field(default="", max_length=2000)


def _require_user(user: dict = Depends(get_current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def _require_owner_or_admin(candidate: str, user: dict) -> dict:
    """Owner-only + admin: the candidate themselves or an ADMIN_EMAILS admin."""
    email = (user.get("email") or "").strip().lower()
    if email == (candidate or "").strip().lower() or is_admin(user):
        return user
    raise HTTPException(status_code=403, detail="Not authorized for this candidate.")


def _require_admin(user: dict = Depends(_require_user)) -> dict:
    """Admin-allowlist-only guard for the full table browser (all 6 tables)."""
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


@admin_router.get("/whoami")
def whoami(user: dict = Depends(_require_user)):
    """Identity + admin flag so the frontend can gate the Admin UI."""
    return {"user": user, "is_admin": is_admin(user)}


@admin_router.get("/tables")
def list_tables(user: dict = Depends(_require_admin)):
    """Table metadata + live counts for the admin table browser."""
    from coach.admin_tables import list_tables as _list_tables

    return {"tables": _list_tables()}


@admin_router.get("/table/{table_name}")
def get_table_rows(
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    q: Optional[str] = None,
    sort: Optional[str] = None,
    order: str = Query("desc", pattern="^(asc|desc)$"),
    candidate: Optional[str] = None,
    skill: Optional[str] = None,
    owner: Optional[str] = None,
    task_id: Optional[str] = None,
    email: Optional[str] = None,
    user_id: Optional[str] = None,
    user: dict = Depends(_require_admin),
):
    """Paginated + searchable rows for any stored table (admin-only)."""
    from coach.admin_tables import TABLE_NAMES, list_rows

    if table_name not in TABLE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown table: {table_name}.")
    filters = {
        "candidate": candidate,
        "skill": skill,
        "owner": owner,
        "task_id": task_id,
        "email": email,
        "user_id": user_id,
    }
    return list_rows(
        table_name, page=page, page_size=page_size, q=q,
        sort=sort, order=order, filters=filters,
    )


@admin_router.get("/table/{table_name}/{row_id}")
def get_table_row(table_name: str, row_id: str, user: dict = Depends(_require_admin)):
    """Full row detail for the admin UI (admin-only)."""
    from coach.admin_tables import TABLE_NAMES, get_row

    if table_name not in TABLE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown table: {table_name}.")
    row = get_row(table_name, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Row not found.")
    return {"row": row}


@admin_router.patch("/table/{table_name}/{row_id}")
def update_table_row(
    table_name: str, row_id: str, body: dict[str, Any], user: dict = Depends(_require_admin)
):
    """Edit whitelisted columns of one row (admin-only)."""
    from coach.admin_tables import TABLE_NAMES, update_row

    if table_name not in TABLE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown table: {table_name}.")
    try:
        updated = update_row(table_name, row_id, body or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=404, detail="Row not found.")
    return {"ok": True, "row": updated}


@admin_router.delete("/table/{table_name}/{row_id}")
def delete_table_row(table_name: str, row_id: str, user: dict = Depends(_require_admin)):
    """Delete one row; tasks cascade to their attempts (admin-only)."""
    from coach.admin_tables import TABLE_NAMES, delete_row

    if table_name not in TABLE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown table: {table_name}.")
    result = delete_row(table_name, row_id)
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail="Row not found.")
    return {"ok": True, "table": table_name, "row_id": row_id, **result}


@admin_router.get("/learners")
def list_learners(user: dict = Depends(_require_user)):
    """List known candidates (derived from sessions/attempts/tasks)."""
    from coach.admin import list_candidates

    return {"learners": [{"candidate": c["candidate"]} for c in list_candidates()]}


@admin_router.get("/skill-states/{candidate}")
def get_skill_states(candidate: str, user: dict = Depends(_require_user)):
    """Return parent app Bayesian SkillState for a candidate's active sessions."""
    from coach.session import Session

    store = get_store()
    active = store.list_by_candidate(candidate)
    if active:
        state = store.get(active[0]["session_id"])
        if state and "session" in state:
            session = Session.from_dict(state["session"])
            return {
                "source": "active_session",
                "session_id": active[0]["session_id"],
                "skill_states": {
                    k: {
                        "score": v.score,
                        "variance": v.variance,
                        "confidence": v.confidence,
                        "questions_answered": v.questions_answered,
                    }
                    for k, v in session.skill_states.items()
                },
            }

    return {"source": "none", "skill_states": {}}


@admin_router.get("/stats")
def get_stats(user: dict = Depends(_require_user)):
    """Return summary counts: tasks, attempts, beliefs, sessions."""
    from coach.admin import stats_summary

    return stats_summary()


@admin_router.get("/tasks")
def list_tasks_admin(
    owner: Optional[str] = None,
    skill: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=500),
    user: dict = Depends(_require_user),
):
    """List task-bank rows with attempt counts (for the Manage tab)."""
    from coach.tasks import list_tasks_for_admin

    tasks = list_tasks_for_admin(owner=owner, skill=skill, q=q, limit=limit)
    return {"tasks": tasks}


@admin_router.patch("/tasks/{task_id}")
def update_task_endpoint(task_id: str, body: TaskContextUpdate, user: dict = Depends(_require_user)):
    """Edit a question's plain-English context notes (owner or admin)."""
    from coach.tasks import get_task, update_task_context

    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    email = (user.get("email") or "").strip().lower()
    if (task.get("owner") or "") != email and not is_admin(user):
        raise HTTPException(status_code=403, detail="Not authorized to edit this task.")
    updated = update_task_context(task_id, body.context_notes or "")
    return {"ok": True, "task": updated}


@admin_router.get("/candidate/{candidate}/summary")
def candidate_summary_endpoint(candidate: str, user: dict = Depends(_require_user)):
    """Dry-run preview: per-table row counts for a candidate (owner or admin)."""
    from coach.admin import candidate_summary

    _require_owner_or_admin(candidate, user)
    return candidate_summary(candidate)


@admin_router.delete("/candidate/{candidate}")
def delete_candidate_endpoint(candidate: str, user: dict = Depends(_require_user)):
    """Full candidate wipe: sessions + attempts + beliefs + owned tasks."""
    from coach.admin import clear_candidate_everything

    _require_owner_or_admin(candidate, user)
    return {"ok": True, **clear_candidate_everything(candidate)}


@admin_router.delete("/tasks/{task_id}")
def delete_task_endpoint(task_id: str, user: dict = Depends(_require_user)):
    """Delete one question plus its attempts (cascade).

    Allowed for the task owner or an ADMIN_EMAILS admin (system seed rows
    are admin-only).
    """
    from coach.tasks import delete_task, get_task

    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    email = (user.get("email") or "").strip().lower()
    if (task.get("owner") or "") != email and not is_admin(user):
        raise HTTPException(status_code=403, detail="Not authorized to delete this task.")
    result = delete_task(task_id)
    return {"ok": True, "task_id": task_id, **result}
