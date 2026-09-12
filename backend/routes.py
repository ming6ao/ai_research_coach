"""API routes for the coaching app (single unified code path).

The app probes and teaches; there is no summative assessment. Sessions are
persisted in ``active_sessions``; "done" is derived from the session JSON via
``pick_next_task``. Guests and signed-in users behave identically.
"""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from typing import Any, Optional

from backend.dependencies import get_store
from backend import google_auth
from backend.auth import (
    AUTH_COOKIE_NAME,
    upsert_google_user,
    create_token,
    revoke_token,
    get_current_user,
    require_user,
)

router = APIRouter(prefix="/api")


class StartRequest(BaseModel):
    initial_question: Optional[str] = Field(default=None, max_length=8000)
    task_ids: Optional[list[str]] = Field(default=None, max_length=100)
    skill: Optional[str] = Field(default=None, max_length=120)


class TaskCreateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    skill: str = Field(default="general", max_length=120)
    scaffold: Optional[str] = Field(default=None, max_length=16000)
    difficulty: int = Field(default=2, ge=1, le=5)
    max_score: int = Field(default=5, ge=1, le=100)
    hints: list[dict[str, Any]] = Field(default_factory=list)
    is_public: bool = False
    context_notes: Optional[str] = Field(default=None, max_length=2000)


class SubmitRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    task_id: str = Field(min_length=1, max_length=128)
    answer: str = Field(min_length=1, max_length=50000)
    hints_used: list[str] = Field(default_factory=list, max_length=50)


class CompleteRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


class SessionOpenRequest(BaseModel):
    id: str = Field(min_length=1, max_length=64)


def _candidate_for(user: dict) -> str:
    if user is not None:
        return user["email"]
    return f"guest-{uuid.uuid4().hex[:8]}"


def _skill_states_dict(session) -> dict:
    return {
        k: {
            "score": v.score,
            "confidence": v.confidence,
            "questions_answered": v.questions_answered,
        }
        for k, v in session.skill_states.items()
    }


def _describe_context(prompt: str, skill: str, explicit: Optional[str] = None) -> str:
    """Author-supplied notes win; otherwise one best-effort LLM description."""
    if explicit is not None and explicit.strip():
        return explicit.strip()[:2000]
    try:
        from coach.task_decomposer import TaskDecomposer

        return TaskDecomposer().describe_task(prompt, skill) or ""
    except Exception:
        return ""


@router.get("/auth/google/url", tags=["auth"], summary="Get Google OAuth URL")
def google_auth_url():
    """Return the Google authorization URL for the frontend to redirect to."""
    try:
        url, _ = google_auth.new_authorization_url()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"url": url}


@router.get("/auth/google/callback", tags=["auth"], summary="Google OAuth callback")
def google_auth_callback(code: str, state: str, response: Response):
    """OAuth callback: verify state, exchange code, upsert user, redirect with token.

    Phase 1 sets the ``ai_coach_token`` HttpOnly cookie in addition to the
    legacy ``?token=`` redirect query param (kept for backward compat with
    the current frontend). Phase 3 will drop the query param.
    """
    if not google_auth.consume_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")
    try:
        tokens = google_auth.exchange_code(code)
        info = google_auth.fetch_userinfo(tokens["access_token"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    email = (info.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email.")
    user = upsert_google_user(email, info.get("name") or "")
    token = create_token(user["id"])
    redirect = RedirectResponse(url=f"{google_auth.frontend_url()}/?token={quote(token)}")
    # Phase 1 (additive): also set an HttpOnly cookie so browsers stop
    # depending on the ?token= query param (removed in Phase 3).
    redirect.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=google_auth.frontend_url().startswith("https://"),
        path="/",
        max_age=30 * 24 * 3600,
    )
    return redirect


@router.post("/auth/logout", tags=["auth"], summary="Revoke bearer token")
def logout(request: Request, response: Response):
    auth = request.headers.get("Authorization", "")
    token = None
    if auth.startswith("Bearer "):
        token = auth[len("Bearer "):].strip()
    if not token:
        token = request.cookies.get(AUTH_COOKIE_NAME, "")
    if token:
        revoke_token(token.strip())
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", tags=["auth"], summary="Current user")
def me(user: dict = Depends(require_user)):
    return {"user": user}


@router.post("/start", tags=["sessions"], summary="Start coaching session")
def start_assessment(req: StartRequest, user: dict = Depends(get_current_user)):
    from coach.session import Session, task_view
    from coach.selection import pick_next_task

    store = get_store()
    candidate = _candidate_for(user)
    is_guest = candidate.startswith("guest-")

    session_id = store.create(candidate)
    # Optional task scoping: a subset of visible task ids to practice.
    scoped_tasks = None
    if req.task_ids:
        from coach.tasks import get_task as _get_task

        scoped_tasks = []
        for tid in req.task_ids:
            t = _get_task(tid)
            if t:
                scoped_tasks.append(t)
    session = Session(candidate, tasks=scoped_tasks or [])

    # If the user typed a custom question, persist it as a task row first.
    custom_task = None
    if req.initial_question and req.initial_question.strip():
        from coach.tasks import create_task as _create_task

        prompt = req.initial_question.strip()
        skill = req.skill or "general"
        custom_task = _create_task(
            prompt=prompt,
            skill=skill,
            owner=candidate,
            difficulty=2,
            max_score=5,
            hints=[],
            source="user",
            # Guests create globally-visible rows; users default to private.
            is_public=is_guest,
            context_notes=_describe_context(prompt, skill),
        )
        session.tasks.insert(0, custom_task)

    if custom_task:
        first_task = task_view(custom_task, session)
    else:
        first_task = pick_next_task(candidate, session)

    store.save(session_id, {"session": session.to_dict()})

    return {
        "session_id": session_id,
        "candidate": session.candidate,
        "message": f"Session started for {session.candidate}.",
        "total_tasks": len(session.tasks),
        "first_task": first_task,
    }


@router.post("/submit", tags=["sessions"], summary="Submit answer for a task")
def submit_answer(req: SubmitRequest, user: dict = Depends(get_current_user)):
    from coach.session import Session, SkillState, task_view
    from coach.score import bayesian_update, effective_score, measurement_variance
    from coach.hints import hint_penalty
    from coach.judge import LLMJudge
    from coach.selection import pick_next_task

    store = get_store()
    state = store.get(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    session = Session.from_dict(state["session"])
    feedback_list = state.get("_feedback_list", [])

    if user is not None and session.candidate != user["email"]:
        raise HTTPException(status_code=403, detail="Not your session.")

    task = next((t for t in session.tasks if t["id"] == req.task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {req.task_id} not found.")

    existing = next((r for r in session.results if r.task_id == req.task_id), None)
    if existing is not None:
        nxt = pick_next_task(session.candidate, session)
        return {
            "result": existing.to_dict(),
            "coach": existing.coach,
            # NOTE: ``feedback`` is a deprecated alias of ``coach.feedback``
            # (kept for backward compat; prefer ``coach``). ``note`` is kept
            # for compat; prefer the ``already_answered`` flag.
            "feedback": (existing.coach or {}).get("feedback") if isinstance(existing.coach, dict) else None,
            "next_task": nxt,
            "remaining": len(session.tasks) - session.index,
            "note": "Already answered.",
            "already_answered": True,
        }

    result, coach = LLMJudge().evaluate(task, req.answer)

    requested = session.viewed_hints.get(req.task_id, [])
    viewed = list(dict.fromkeys(list(req.hints_used or []) + requested))

    skill_id = task["skill"]
    state_obj = session.get_skill_state(skill_id)

    penalty = hint_penalty(task, viewed)
    observation = effective_score(result.fraction, penalty)
    obs_variance = measurement_variance(task.get("difficulty", 1), state_obj.score)
    new_score, new_variance = bayesian_update(
        state_obj.score, state_obj.variance, observation, obs_variance
    )

    session.skill_states[skill_id] = SkillState(
        score=new_score,
        variance=new_variance,
        questions_answered=state_obj.questions_answered + 1,
        evidence=state_obj.evidence + [result.rationale],
        hints_used=state_obj.hints_used + viewed,
    )
    try:
        from coach.tasks import record_attempt as _record_attempt
        from coach.tasks import save_skill_belief as _save_belief

        _record_attempt(
            session.candidate,
            task["id"],
            observation,
            result.score,
            result.max_score,
            viewed,
        )
        _save_belief(
            session.candidate,
            skill_id,
            new_score,
            new_variance,
            state_obj.questions_answered + 1,
        )
    except Exception:
        pass

    feedback_entry = {
        "task_id": task["id"],
        "prompt": task["prompt"],
        "type": "code",
        "skill": task["skill"],
        "user_answer": req.answer,
        "result": result.to_dict(),
        "feedback": coach.feedback,
        "coach": coach.to_dict(),
        "hints_used": viewed,
        "scored": True,
    }
    feedback_list.append(feedback_entry)

    session.asked_task_ids.add(req.task_id)
    session.results.append(result)
    session.index += 1

    skill_update = {
        "skill": skill_id,
        "new_score": new_score,
        "new_confidence": session.get_skill_state(skill_id).confidence,
        "hints_used": viewed,
    }

    # Hybrid next-task selection: pending generated task, then judge-driven
    # follow-up, then the EIG bank picker.
    next_task = None
    try:
        next_task = pick_next_task(
            session.candidate,
            session,
            last_submission={"task": task, "result": result, "coach": coach},
        )
    except Exception:
        from coach.picker import next_task as next_task_bank
        nxt = next_task_bank(session)
        next_task = task_view(nxt, session) if nxt else None

    state["session"] = session.to_dict()
    store.save(req.session_id, state, feedback_list)

    return {
        "result": result.to_dict(),
        # Deprecated alias of ``coach.feedback`` (kept for compat).
        "feedback": coach.feedback,
        "coach": coach.to_dict(),
        "next_task": next_task,
        "remaining": len(session.tasks) - session.index,
        "skill_update": skill_update,
        "already_answered": False,
    }


@router.post("/tasks", tags=["tasks"], status_code=status.HTTP_201_CREATED, summary="Create task")
def create_task_endpoint(req: TaskCreateRequest, user: dict = Depends(get_current_user)):
    from coach.tasks import create_task as _create_task

    if not req.prompt.strip():
        raise HTTPException(status_code=422, detail="Prompt must not be empty.")
    candidate = _candidate_for(user)
    is_guest = candidate.startswith("guest-")
    task = _create_task(
        prompt=req.prompt.strip(),
        skill=req.skill or "general",
        owner=candidate,
        scaffold=req.scaffold,
        difficulty=req.difficulty or 2,
        max_score=req.max_score or 5,
        hints=req.hints or [],
        source="user",
        is_public=bool(req.is_public or is_guest),
        context_notes=_describe_context(req.prompt.strip(), req.skill or "general", req.context_notes),
    )
    return {"task": task}


@router.get("/tasks", tags=["tasks"], summary="List visible tasks")
def list_tasks_endpoint(skill: Optional[str] = None, user: dict = Depends(get_current_user)):
    from coach.tasks import list_visible_tasks

    # Guests without a stable id list as system: seed + public tasks.
    # (Own in-session custom rows are returned via /start, not here.)
    candidate = user["email"] if user is not None else "system"
    tasks = list_visible_tasks(candidate, skill=skill)
    return {"tasks": tasks}


@router.get("/tasks/{task_id}", tags=["tasks"], summary="Get task by id")
def get_task_endpoint(task_id: str, user: dict = Depends(get_current_user)):
    from coach.tasks import get_task as _get_task

    task = _get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"task": task}


@router.post("/complete", tags=["sessions"], summary="Complete session")
def complete_session(req: CompleteRequest, user: dict = Depends(get_current_user)):
    from coach.session import Session

    store = get_store()
    state = store.get(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    session = Session.from_dict(state["session"])
    if user is not None and session.candidate != user["email"]:
        raise HTTPException(status_code=403, detail="Not your session.")

    # The session row stays in active_sessions for history/resume; "done" is
    # derived from the session JSON (pick_next_task returns None).
    return {
        "done": True,
        "skill_states": _skill_states_dict(session),
    }


@router.post("/session/open", tags=["sessions"], summary="Reopen session")
def open_session(req: SessionOpenRequest, user: dict = Depends(get_current_user)):
    from coach.session import Session
    from coach.selection import pick_next_task

    store = get_store()
    state = store.get(req.id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    session = Session.from_dict(state["session"])
    feedback_list = state.get("_feedback_list", [])

    if user is not None and session.candidate != user["email"]:
        raise HTTPException(status_code=403, detail="Not your session.")
    if user is None and not session.candidate.startswith("guest-"):
        raise HTTPException(
            status_code=403,
            detail="Guests can only resume their own sessions. Log in to open this one.",
        )

    task = pick_next_task(session.candidate, session)

    return {
        "session_id": req.id,
        "candidate": session.candidate,
        "total_tasks": len(session.tasks),
        "task_index": session.index,
        "current_task": task,
        "results": feedback_list,
        "skill_states": _skill_states_dict(session),
    }


@router.get("/sessions", tags=["sessions"], summary="List my sessions")
def list_sessions(user: dict = Depends(get_current_user)):
    from coach.session import Session
    from coach.selection import pick_next_task

    store = get_store()
    if user is None:
        return {"sessions": []}
    candidate = user["email"]

    sessions = []
    for s in store.list_by_candidate(candidate):
        state = store.get(s["session_id"])
        done = False
        if state and "session" in state:
            session = Session.from_dict(state["session"])
            try:
                done = pick_next_task(candidate, session) is None
            except Exception:
                done = session.index >= len(session.tasks)
        sessions.append({
            "id": s["session_id"],
            "candidate": s["candidate"],
            "done": done,
            "updated_at": s["updated_at"],
        })

    sessions.sort(key=lambda s: s["updated_at"], reverse=True)
    return {"sessions": sessions}


@router.delete("/sessions/active/{session_id}", tags=["sessions"], summary="Delete active session")
def delete_active_session(session_id: str, user: dict = Depends(get_current_user)):
    store = get_store()
    state = store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if user is not None:
        from coach.session import Session
        sess = Session.from_dict(state["session"])
        if sess.candidate != user["email"]:
            raise HTTPException(status_code=403, detail="Not your session.")
    store.delete(session_id)
    return {"ok": True}


@router.delete("/sessions/clear/{candidate}", tags=["sessions"], summary="Clear candidate data")
def clear_candidate_data(candidate: str, user: dict = Depends(get_current_user)):
    """Clear all data for a candidate.

    When authenticated the path ``candidate`` is ignored and the caller's own
    account is cleared (legacy behavior kept for compat; prefer ``DELETE /me``
    in the v1 API).
    """
    from coach.admin import clear_candidate_everything

    if user is not None:
        candidate = user["email"]
    result = clear_candidate_everything(candidate)
    return {
        "ok": True,
        "deleted": result["deleted"]["total"],
        "deleted_by_table": result["deleted"],
    }
