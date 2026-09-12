"""API routes for the coaching app (single unified code path).

The app probes and teaches; there is no summative assessment. Sessions are
persisted in ``active_sessions``; "done" is derived from the session JSON via
``pick_next_task``. Guests and signed-in users behave identically.
"""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional

from backend.dependencies import get_store
from backend import google_auth
from backend.auth import (
    upsert_google_user,
    create_token,
    revoke_token,
    get_current_user,
)

router = APIRouter(prefix="/api", tags=["assessment"])


class StartRequest(BaseModel):
    initial_question: Optional[str] = None
    task_ids: Optional[list] = None
    skill: Optional[str] = None


class TaskCreateRequest(BaseModel):
    prompt: str
    skill: Optional[str] = "general"
    scaffold: Optional[str] = None
    difficulty: Optional[int] = 2
    max_score: Optional[int] = 5
    hints: Optional[list] = None
    expected_time_min: Optional[float] = None
    is_public: Optional[bool] = False
    context_notes: Optional[str] = None


class SubmitRequest(BaseModel):
    session_id: str
    task_id: str
    answer: str
    hints_used: Optional[list] = None


class CompleteRequest(BaseModel):
    session_id: str


class SessionOpenRequest(BaseModel):
    id: str


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


@router.get("/auth/google/url")
def google_auth_url():
    """Return the Google authorization URL for the frontend to redirect to."""
    try:
        url, _ = google_auth.new_authorization_url()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"url": url}


@router.get("/auth/google/callback")
def google_auth_callback(code: str, state: str):
    """OAuth callback: verify state, exchange code, upsert user, redirect with token."""
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
    return RedirectResponse(url=f"{google_auth.frontend_url()}/?token={quote(token)}")


@router.post("/auth/logout")
def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        revoke_token(auth[len("Bearer "):].strip())
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict = Depends(get_current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return {"user": user}


@router.post("/start")
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


@router.post("/submit")
def submit_answer(req: SubmitRequest, user: dict = Depends(get_current_user)):
    from coach.session import Session, SkillState, task_view
    from coach.score import bayesian_update, effective_score, measurement_variance
    from coach.hints import hint_penalty
    from coach.judge import LLMJudge
    from coach.selection import pick_next_task

    store = get_store()
    state = store.get(req.session_id)
    if state is None:
        raise HTTPException(status_code=400, detail="No active session.")

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
            "next_task": nxt,
            "remaining": len(session.tasks) - session.index,
            "note": "Already answered.",
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
        "feedback": coach.feedback,
        "coach": coach.to_dict(),
        "next_task": next_task,
        "remaining": len(session.tasks) - session.index,
        "skill_update": skill_update,
    }


@router.post("/tasks")
def create_task_endpoint(req: TaskCreateRequest, user: dict = Depends(get_current_user)):
    from coach.tasks import create_task as _create_task

    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required.")
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
        expected_time_min=req.expected_time_min,
        source="user",
        is_public=bool(req.is_public or is_guest),
        context_notes=_describe_context(req.prompt.strip(), req.skill or "general", req.context_notes),
    )
    return {"task": task}


@router.get("/tasks")
def list_tasks_endpoint(skill: Optional[str] = None, user: dict = Depends(get_current_user)):
    from coach.tasks import list_visible_tasks

    candidate = _candidate_for(user)
    # Guests without a stable id still see public/seed tasks.
    visible_for = user["email"] if user is not None else "system"
    if candidate.startswith("guest-"):
        # Guest rows are public, so listing as system covers seed+public.
        # Own in-session custom rows are returned via /start, not here.
        pass
    tasks = list_visible_tasks(visible_for if user is None else candidate, skill=skill)
    return {"tasks": tasks}


@router.get("/tasks/{task_id}")
def get_task_endpoint(task_id: str, user: dict = Depends(get_current_user)):
    from coach.tasks import get_task as _get_task

    task = _get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"task": task}


@router.post("/complete")
def complete_session(req: CompleteRequest, user: dict = Depends(get_current_user)):
    from coach.session import Session

    store = get_store()
    state = store.get(req.session_id)
    if state is None:
        raise HTTPException(status_code=400, detail="No active session.")

    session = Session.from_dict(state["session"])
    if user is not None and session.candidate != user["email"]:
        raise HTTPException(status_code=403, detail="Not your session.")

    # The session row stays in active_sessions for history/resume; "done" is
    # derived from the session JSON (pick_next_task returns None).
    return {
        "done": True,
        "skill_states": _skill_states_dict(session),
    }


@router.post("/session/open")
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


@router.get("/sessions")
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


@router.delete("/sessions/active/{session_id}")
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


@router.delete("/sessions/clear/{candidate}")
def clear_candidate_data(candidate: str, user: dict = Depends(get_current_user)):
    from coach.admin import clear_candidate_everything

    if user is not None:
        candidate = user["email"]
    result = clear_candidate_everything(candidate)
    return {
        "ok": True,
        "deleted": result["deleted"]["total"],
        "deleted_by_table": result["deleted"],
    }
