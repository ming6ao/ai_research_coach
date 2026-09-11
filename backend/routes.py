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
    from learner.engine import LearnerEngine, pick_next_task

    store = get_store()
    candidate = _candidate_for(user)

    session_id = store.create(candidate)
    session = Session(candidate)

    # If the user typed a custom question, inject it as the first task.
    custom_task = None
    if req.initial_question and req.initial_question.strip():
        custom_task = {
            "id": f"custom_{uuid.uuid4().hex[:8]}",
            "skill": "general",
            "difficulty": 2,
            "prompt": req.initial_question.strip(),
            "max_score": 5,
            "hints": [],
        }
        session.tasks.insert(0, custom_task)

    if custom_task:
        first_task = task_view(custom_task, session)
    else:
        first_task = pick_next_task(candidate, session)

    # Bootstrap the learner knowledge graph from the picked task.
    learner = None
    try:
        engine = LearnerEngine()
        engine.ensure_learner(candidate)
        if first_task is not None:
            boot = engine.bootstrap_task(first_task)
            learner = {
                "learner_id": str(engine.learner_id(candidate)),
                "primary_node_slug": boot.get("primary_node_slug"),
            }
    except Exception:
        # Never let learner integration break session startup.
        learner = None

    store.save(session_id, {"session": session.to_dict()})

    return {
        "session_id": session_id,
        "candidate": session.candidate,
        "message": f"Session started for {session.candidate}.",
        "total_tasks": len(session.tasks),
        "first_task": first_task,
        "learner": learner,
    }


@router.post("/submit")
def submit_answer(req: SubmitRequest, user: dict = Depends(get_current_user)):
    from coach.session import Session, SkillState, task_view
    from coach.score import bayesian_update, effective_score, measurement_variance
    from coach.hints import hint_penalty
    from coach.judge import LLMJudge
    from learner.engine import LearnerEngine, pick_next_task

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

    # Feed the judge result into the learner model (evidence -> state ->
    # frontier -> policy). Never allowed to break the response.
    engine = LearnerEngine()
    learner_update = None
    snapshot = None
    try:
        learner_update = engine.record_submission(
            session.candidate, task, result, coach, viewed_hints=viewed
        )
        snapshot = engine.learner_snapshot(session.candidate)
    except Exception:
        learner_update = None
        snapshot = None

    # Hybrid next-task selection: pending generated task, then frontier
    # remediation, then the EIG bank picker.
    next_task = None
    try:
        next_task = pick_next_task(
            session.candidate,
            session,
            last_submission={
                "task": task,
                "result": result,
                "learner_update": learner_update,
                "learner_snapshot": snapshot,
            },
            engine=engine,
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
        "learner_update": learner_update,
    }


@router.post("/complete")
def complete_session(req: CompleteRequest, user: dict = Depends(get_current_user)):
    from coach.session import Session
    from learner.engine import LearnerEngine

    store = get_store()
    state = store.get(req.session_id)
    if state is None:
        raise HTTPException(status_code=400, detail="No active session.")

    session = Session.from_dict(state["session"])
    if user is not None and session.candidate != user["email"]:
        raise HTTPException(status_code=403, detail="Not your session.")

    learner = None
    try:
        learner = LearnerEngine().learner_snapshot(session.candidate)
    except Exception:
        learner = None

    # The session row stays in active_sessions for history/resume; "done" is
    # derived from the session JSON (pick_next_task returns None).
    return {
        "done": True,
        "skill_states": _skill_states_dict(session),
        "learner": learner,
    }


@router.post("/session/open")
def open_session(req: SessionOpenRequest, user: dict = Depends(get_current_user)):
    from coach.session import Session
    from learner.engine import LearnerEngine, pick_next_task

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

    learner = None
    try:
        learner = LearnerEngine().learner_snapshot(session.candidate)
    except Exception:
        learner = None

    return {
        "session_id": req.id,
        "candidate": session.candidate,
        "total_tasks": len(session.tasks),
        "task_index": session.index,
        "current_task": task,
        "results": feedback_list,
        "skill_states": _skill_states_dict(session),
        "learner": learner,
    }


@router.get("/sessions")
def list_sessions(user: dict = Depends(get_current_user)):
    from coach.session import Session
    from learner.engine import pick_next_task

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
    store = get_store()
    from learner.engine import clear_learner_data

    if user is not None:
        candidate = user["email"]
    active_deleted = store.delete_by_candidate(candidate)
    learner_deleted = clear_learner_data(candidate)
    return {
        "ok": True,
        "deleted": active_deleted + learner_deleted,
    }