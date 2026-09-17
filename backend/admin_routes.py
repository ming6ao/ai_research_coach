"""Admin API routes.

Covers admin seed authoring, activity reset, and owner-or-admin candidate
wipes. Task CRUD lives in the v1 API (``/api/v1/tasks*``, owner-or-admin
guarded); overall progress lives in session views (``/api/v1/sessions*``).
"""

import uuid

from fastapi import APIRouter, HTTPException, Depends

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
    """Admin-allowlist-only guard for admin-only endpoints."""
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
    """Persist a new public system-authored task (owner ``system``).

    The task bank lives in the database, so admin-authored questions are just
    ``tasks`` rows created through this API (``source="seed_admin"``) — there
    is no code catalog to stay in sync with.
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
            language=req.language,
            version_index=req.version_index,
            depends_on_task_id=req.depends_on_task_id,
            version_root_id=req.version_root_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"data": task}


@admin_router.get("/reset/preview")
def reset_preview(user: dict = Depends(_require_admin)):
    """Dry-run: which app-data rows a DB reset would wipe (users/auth kept)."""
    from coach.db import reset_database

    return {"ok": True, **reset_database(preview=True)}


@admin_router.post("/reset")
def reset_database_endpoint(user: dict = Depends(_require_admin)):
    """Wipe activity/progress data; preserve identity/auth and the task bank.

    Deletes sessions, steps, beliefs, and shares (users/auth tokens and the
    ``tasks`` table are preserved — the DB is the source of truth for
    questions). Admin-only.
    """
    from coach.db import reset_database

    return {"ok": True, **reset_database(preview=False)}


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
