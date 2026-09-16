"""Admin/debug API routes.

Covers the generic table browser (admin-only) plus owner-or-admin candidate
wipes. Task CRUD lives in the v1 API (``/api/v1/tasks*``, owner-or-admin
guarded); overall progress lives in session views (``/api/v1/sessions*``).
"""

import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Depends, Query

from backend.auth import get_current_user, is_admin
from backend.v1.schemas import AdminSeedCreateRequest

admin_router = APIRouter(prefix="/admin", tags=["admin"])


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


@admin_router.get("/taxonomy", summary="Tag/family/task-type vocabulary for the admin seed form")
def taxonomy(user: dict = Depends(_require_admin)):
    """Closed tag vocabulary (single source of truth) so the admin seed
    form's dropdowns never drift from ``coach/taxonomy.py``."""
    from coach.taxonomy import FAMILIES, TAGS, TASK_TYPES

    return {
        "families": FAMILIES,
        "tags": TAGS,
        "task_types": list(TASK_TYPES),
    }


@admin_router.post("/seeds", summary="Create an admin-authored seed question")
def create_seed(req: AdminSeedCreateRequest, user: dict = Depends(_require_admin)):
    """Persist a new builtin-style seed task (owner ``system``, public).

    Admin-authored seeds use ``source="seed_admin"`` so they are never
    touched by stale-seed cleanup (which only targets ``source="seed"``).
    They are runtime-only: a DB reset re-bootstraps the bank from the code
    catalog and wipes them.
    """
    from coach.tasks import SYSTEM_OWNER, create_task
    from coach.taxonomy import validate as validate_tags

    # Reused session helper (LLM context notes) — same path as v1 task create.
    from backend.v1.sessions import _describe_context

    if not req.prompt.strip():
        raise HTTPException(status_code=422, detail="Prompt must not be empty.")
    try:
        tags = validate_tags(req.tags)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        task = create_task(
            prompt=req.prompt.strip(),
            owner=SYSTEM_OWNER,
            scaffold=req.scaffold,
            difficulty=req.difficulty,
            max_score=req.max_score,
            parts=req.parts,
            source="seed_admin",
            is_public=True,
            task_id=f"seed_admin_{uuid.uuid4().hex[:8]}",
            context_notes=_describe_context(req.prompt.strip(), req.context_notes),
            tags=tags,
            task_type=req.task_type or "implement",
            version_index=req.version_index,
            depends_on_task_id=req.depends_on_task_id,
            version_root_id=req.version_root_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"data": task}


@admin_router.get("/tables")
def list_tables(user: dict = Depends(_require_admin)):
    """Table metadata + live counts for the admin table browser."""
    from coach.admin_tables import list_tables as _list_tables

    return {"tables": _list_tables()}


@admin_router.get("/coverage", summary="Seed + per-candidate coverage report")
def coverage_report_endpoint(user: dict = Depends(_require_admin)):
    """Per-family/per-tag seed coverage + per-candidate asked counts."""
    from coach.seed_bank import coverage_report

    return {"data": coverage_report()}


@admin_router.get("/table/{table_name}")
def get_table_rows(
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    q: Optional[str] = None,
    sort: Optional[str] = None,
    order: str = Query("desc", pattern="^(asc|desc)$"),
    candidate: Optional[str] = None,
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


@admin_router.get("/reset/preview")
def reset_preview(user: dict = Depends(_require_admin)):
    """Dry-run: which app-data rows a DB reset would wipe (users/auth kept)."""
    from coach.db import reset_database

    return {"ok": True, **reset_database(preview=True)}


@admin_router.post("/reset")
def reset_database_endpoint(user: dict = Depends(_require_admin)):
    """Wipe app data and re-bootstrap the question bank from SEED_CATALOG.

    Deletes sessions, steps, beliefs, shares, and tasks (users/auth tokens
    preserved), then re-seeds the builtin catalog so the DB is in sync with
    the code. Admin-only.
    """
    from coach.db import reset_database

    return {"ok": True, **reset_database(preview=False)}


@admin_router.get("/stale-seeds/preview")
def stale_seeds_preview(user: dict = Depends(_require_admin)):
    """Dry-run: which stale seed rows + their dependents would be deleted."""
    from coach.admin import stale_seed_cleanup

    return {"ok": True, **stale_seed_cleanup(preview=True)}


@admin_router.delete("/stale-seeds")
def stale_seeds_delete(user: dict = Depends(_require_admin)):
    """Delete stale seed rows and everything referencing them (admin-only)."""
    from coach.admin import stale_seed_cleanup

    return {"ok": True, **stale_seed_cleanup(preview=False)}


@admin_router.get("/guest-data/preview")
def guest_data_preview(user: dict = Depends(_require_admin)):
    """Dry-run: which guest-scoped rows would be deleted."""
    from coach.admin import guest_data_cleanup

    return {"ok": True, **guest_data_cleanup(preview=True)}


@admin_router.delete("/guest-data")
def guest_data_delete(user: dict = Depends(_require_admin)):
    """Delete all guest-scoped rows (sessions, steps, beliefs, owned tasks)."""
    from coach.admin import guest_data_cleanup

    return {"ok": True, **guest_data_cleanup(preview=False)}


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
