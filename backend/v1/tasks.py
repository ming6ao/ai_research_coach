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
    tag: Optional[str] = None,
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
    if tag and tag.strip():
        from coach.taxonomy import family_of, is_valid_family, is_valid_tag, normalize_tag

        target = normalize_tag(tag.strip())
        if target is None:
            target = tag.strip()
        want_family = is_valid_family(target)
        if not want_family and not is_valid_tag(target):
            target = None
        out = []
        for t in tasks:
            tags = t.get("tags") or {}
            prim = tags.get("primary")
            sec = tags.get("secondary") or []
            if want_family:
                hit = (family_of(prim) == target) or any(
                    family_of(s) == target for s in sec
                )
            else:
                hit = prim == target or target in sec
            if hit:
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

    if not req.prompt.strip():
        raise HTTPException(status_code=422, detail="Prompt must not be empty.")
    try:
        tags = validate_tags(req.tags)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    candidate = resolve_candidate(user, request)
    is_guest = candidate.startswith("guest-")
    task = _create_task(
        prompt=req.prompt.strip(),
        owner=candidate,
        scaffold=req.scaffold,
        difficulty=req.difficulty,
        max_score=req.max_score,
        parts=req.parts,
        source="user",
        is_public=bool(req.is_public or is_guest),
        context_notes=_describe_context(
            req.prompt.strip(), req.context_notes
        ),
        tags=tags,
        task_type=req.task_type or "implement",
        language=req.language,
        version_index=req.version_index,
        depends_on_task_id=req.depends_on_task_id,
        version_root_id=req.version_root_id,
    )
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
