"""v1 task resources: canonical REST replacement for /api/tasks* and the
bespoke /admin/tasks* endpoints (single owner-or-admin-guarded CRUD).

- GET    /api/v1/tasks?q=&page=&page_size=  -> {data: [...], meta}
- POST   /api/v1/tasks                             -> 201 {data: task}
- GET    /api/v1/tasks/{id}                        -> {data: task}
- PATCH  /api/v1/tasks/{id}                        -> {data: task} (owner or admin)
- DELETE /api/v1/tasks/{id}                        -> {data: {task_id, deleted_task, deleted_attempts}}
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.auth import get_current_user, is_admin
from backend.dependencies import resolve_candidate
from backend.v1.pagination import PageParams, paginate
from backend.v1.schemas import TaskCreateRequest, TaskPatchRequest

# Reused session helper (LLM context notes).
from backend.v1.sessions import _describe_context

router = APIRouter(prefix="/tasks", tags=["v1:tasks"])


def _check_task_owner(task: dict, user: Optional[dict]) -> None:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    email = (user.get("email") or "").strip().lower()
    if (task.get("owner") or "") != email and not is_admin(user):
        raise HTTPException(status_code=403, detail="Not authorized for this task.")


@router.get("", summary="List visible tasks")
def list_tasks(
    q: Optional[str] = None,
    node: Optional[str] = None,
    page: PageParams = Depends(),
    user: Optional[dict] = Depends(get_current_user),
):
    from coach.tasks import list_visible_tasks

    # Guests without a stable id list as system: public + own-visible tasks.
    candidate = user["email"] if user is not None else "system"
    tasks = list_visible_tasks(candidate)
    if q and q.strip():
        needle = q.strip().lower()
        tasks = [t for t in tasks if needle in (t.get("prompt") or "").lower()]
    target_raw = (node or "").strip()
    if target_raw:
        from coach.taxonomy import ancestors, resolve_node

        target = resolve_node(target_raw)

        def _matches(n: Optional[str]) -> bool:
            canon = resolve_node(n)
            if canon is None or target is None:
                return False
            return canon == target or target in ancestors(canon)

        if target is not None:
            out = []
            for t in tasks:
                tags = t.get("tags") or {}
                candidates = [tags.get("primary"), *(tags.get("secondary") or [])]
                if any(_matches(n) for n in candidates):
                    out.append(t)
            tasks = out
    items, meta = paginate(tasks, page.page, page.page_size)
    return {"data": items, "meta": meta}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create task")
def create_task(
    req: TaskCreateRequest,
    user: Optional[dict] = Depends(get_current_user),
    request: Request = None,
):
    from coach.tasks import create_task as _create_task
    from coach.taxonomy import validate as validate_tags

    if not req.parts:
        raise HTTPException(
            status_code=422, detail="At least one part is required."
        )
    # Task-level tags are optional: when omitted, ``create_task`` derives them
    # from the steps' own tags (each step is already required to be tagged).
    tags = None
    if req.tags is not None:
        try:
            tags = validate_tags(req.tags)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    candidate = resolve_candidate(user, request)
    is_guest = candidate.startswith("guest-")
    # Context notes describe the first thing the learner sees: the first step.
    source_text = str((req.parts or [{}])[0].get("prompt") or "")
    try:
        task = _create_task(
            owner=candidate,
            scaffold=req.scaffold,
            parts=req.parts,
            source="user",
            is_public=bool(req.is_public or is_guest),
            context_notes=_describe_context(source_text, req.context_notes),
            tags=tags,
            task_type=req.task_type or "implement",
            language=req.language,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"data": task}


@router.get("/{task_id}", summary="Get task by id")
def get_task(task_id: str, user: Optional[dict] = Depends(get_current_user)):
    from coach.tasks import get_task as _get_task

    _ = user  # listing is visibility-agnostic by id (unchanged legacy behavior)
    task = _get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"data": task}


@router.patch("/{task_id}", summary="Update task (owner or admin)")
def patch_task(
    task_id: str, req: TaskPatchRequest, user: Optional[dict] = Depends(get_current_user)
):
    from coach.tasks import get_task as _get_task
    from coach.tasks import update_task as _update_task

    task = _get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    _check_task_owner(task, user)
    if req.owner is not None and not is_admin(user):
        raise HTTPException(
            status_code=403, detail="Only admins can change task ownership."
        )
    try:
        updated = _update_task(task_id, **req.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"data": updated}


@router.delete("/{task_id}", summary="Delete task (owner or admin)")
def delete_task(task_id: str, user: Optional[dict] = Depends(get_current_user)):
    from coach.tasks import delete_task as _delete_task
    from coach.tasks import get_task as _get_task

    task = _get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    _check_task_owner(task, user)
    result = _delete_task(task_id)
    return {"data": {"task_id": task_id, **result}}
