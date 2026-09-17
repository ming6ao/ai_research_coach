"""Admin API routes.

Covers activity reset, the taxonomy vocabulary, and owner-or-admin candidate
wipes. Task CRUD lives in the v1 API (``/api/v1/tasks*``, owner-or-admin
guarded); overall progress lives in session views (``/api/v1/sessions*``).
"""

from fastapi import APIRouter, HTTPException, Depends

from backend.auth import get_current_user, is_admin

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


@admin_router.get("/taxonomy", summary="Domain/area/skill/task-type vocabulary")
def taxonomy(user: dict = Depends(_require_admin)):
    """Closed vocabulary (single source of truth) so the UI's tag dropdowns
    never drift from ``coach/taxonomy.py``."""
    from coach.taxonomy import AREAS, DOMAINS, LEAF_NODES, TASK_TYPES, TAXONOMY

    return {
        "tree": TAXONOMY,
        "domains": DOMAINS,
        "areas": AREAS,
        "skills": LEAF_NODES,
        "task_types": list(TASK_TYPES),
    }


@admin_router.get("/reset/preview")
def reset_preview(wipe_tasks: bool = False, user: dict = Depends(_require_admin)):
    """Dry-run: which app-data rows a DB reset would wipe (users/auth kept)."""
    from coach.db import reset_database

    return {"ok": True, **reset_database(preview=True, wipe_tasks=wipe_tasks)}


@admin_router.post("/reset")
def reset_database_endpoint(wipe_tasks: bool = False, user: dict = Depends(_require_admin)):
    """Wipe activity/progress data; preserve identity/auth.

    Deletes sessions, steps, beliefs, and shares. The task bank (``tasks``) is
    preserved by default — pass ``?wipe_tasks=true`` to also delete every task
    (used when re-authoring questions against a new taxonomy). Admin-only.
    """
    from coach.db import reset_database

    return {"ok": True, **reset_database(preview=False, wipe_tasks=wipe_tasks)}


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
