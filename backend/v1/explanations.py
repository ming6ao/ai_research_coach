"""v1 selection-driven explanations ("Explain this").

- POST /api/v1/sessions/{id}/explanations  -> 201 {data: explanation}
- GET  /api/v1/sessions/{id}/explanations  -> {data: [explanation, ...], meta}

An explanation is a comprehension aid for a highlighted passage, not a scored
answer: these routes never touch the belief system or the step trajectory.
Identical requests within a session are served from the stored row
(``cached: true``) without a second LLM call.
"""

import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from backend.auth import get_current_user
from backend.dependencies import get_store
from backend.v1.schemas import ExplainCreateRequest
from backend.v1.sessions import _check_owner, _load_session
from coach.config import MODEL

router = APIRouter(prefix="/sessions", tags=["v1:explanations"])

ALLOWED_SOURCE_KINDS = {"question", "coaching", "context", "code", "other"}


def _request_hash(
    task_id: str, step_key: str, selected_text: str, context: str, question: str
) -> str:
    payload = "\x1f".join([task_id, step_key, selected_text, context, question])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _active_part(session, task: dict, step_key: Optional[str]):
    """Resolve the (part, 0-based phase index) an explanation is grounded in.

    An explicit ``step_key`` must belong to the task; otherwise the session's
    active step is used (falling back to the last step once the task is done,
    so review-time explanations still get context).
    """
    from coach.session import completed_phases, effective_parts

    parts = effective_parts(task)
    if step_key:
        for i, part in enumerate(parts):
            if part.get("key") == step_key:
                return part, i
        raise HTTPException(status_code=422, detail=f"Unknown step key: {step_key!r}.")
    idx = completed_phases(task, session)
    if 0 <= idx < len(parts):
        return parts[idx], idx
    if parts:
        return parts[-1], len(parts) - 1
    return None, 0


@router.post(
    "/{session_id}/explanations",
    status_code=status.HTTP_201_CREATED,
    summary="Explain a highlighted passage",
)
def create_explanation(
    session_id: str,
    req: ExplainCreateRequest,
    user: Optional[dict] = Depends(get_current_user),
):
    from coach.explainer import Explainer
    from coach.explanations import find_cached, get_explanation, insert_explanation

    store = get_store()
    session, _state = _load_session(store, session_id)
    _check_owner(session, user)

    task = next((t for t in session.tasks if t["id"] == req.task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {req.task_id} not found.")

    selection = (req.selected_text or "").strip()
    if not selection:
        raise HTTPException(status_code=422, detail="Selected text must not be empty.")
    context = (req.context or "").strip()[:800]
    question = (req.question or "").strip()

    # A follow-up inherits its parent's task/step (and grounds the call in the
    # parent explanation) unless the client supplied its own.
    parent = None
    parent_id = req.parent_id
    if parent_id:
        parent = get_explanation(parent_id)
        if parent is None or parent["session_id"] != session_id:
            raise HTTPException(status_code=404, detail="Parent explanation not found.")
        task_id = req.task_id or parent.get("task_id") or ""
        step_key = req.step_key or parent.get("step_key")
    else:
        task_id = req.task_id
        step_key = req.step_key

    part, phase_index = _active_part(session, task, step_key)
    resolved_step_key = (part or {}).get("key") if part else step_key
    source_kind = req.source_kind if req.source_kind in ALLOWED_SOURCE_KINDS else "other"

    request_hash = _request_hash(task_id, resolved_step_key or "", selection, context, question)
    if not question:  # cache only first-level explanations, not conversations
        cached = find_cached(session_id, request_hash)
        if cached is not None:
            cached["cached"] = True
            return {"data": cached}

    try:
        result = Explainer().explain(
            selection,
            context=context,
            step_prompt=str((part or {}).get("prompt") or task.get("prompt") or ""),
            task_notes=str(task.get("context_notes") or ""),
            language=str(task.get("language") or "python"),
            question=question,
            prior_explanation=str((parent or {}).get("explanation") or ""),
        )
    except RuntimeError as exc:
        # Retryable from the client; log once at the route boundary.
        raise HTTPException(
            status_code=502,
            detail="Could not generate an explanation right now. Please retry.",
        ) from exc

    row = insert_explanation(
        session_id,
        session.candidate,
        task_id=task_id,
        step_key=resolved_step_key,
        phase_index=phase_index,
        source_kind=source_kind,
        selected_text=selection,
        context_text=context,
        question=question or None,
        parent_id=parent_id,
        request_hash=request_hash,
        title=result.get("title", ""),
        explanation=result.get("explanation", ""),
        related_terms=result.get("related_terms") or [],
        model=MODEL,
        status="ok",
    )
    row["cached"] = False
    return {"data": row}


@router.get(
    "/{session_id}/explanations",
    summary="List a session's explanations",
)
def list_session_explanations(
    session_id: str,
    user: Optional[dict] = Depends(get_current_user),
):
    from coach.explanations import list_explanations

    store = get_store()
    session, _state = _load_session(store, session_id)
    _check_owner(session, user)
    items = list_explanations(session_id)
    return {"data": items, "meta": {"total": len(items)}}
