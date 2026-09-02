"""API routes wrapping the agent's tool functions."""

import sys
import json
import uuid
from pathlib import Path
from urllib.parse import quote

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional, List

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
    candidate_name: str
    initial_question: Optional[str] = None


class SubmitRequest(BaseModel):
    session_id: str
    task_id: str
    answer: str
    hints_used: Optional[List[str]] = None


class ReportRequest(BaseModel):
    session_id: str


class SessionOpenRequest(BaseModel):
    id: str
    status: str  # "active" or "completed"


class _FakeToolContext:
    def __init__(self, state: dict):
        self._state = state

    @property
    def state(self):
        return self._state

    def __setitem__(self, key, value):
        self._state[key] = value

    def __getitem__(self, key):
        return self._state[key]


@router.get("/session/last")
def find_last_session(candidate: str):
    store = get_store()
    sid = store.find_last_by_candidate(candidate)
    if sid is None:
        return {"session_id": None}
    return {"session_id": sid}


@router.get("/sessions/active")
def list_active_sessions():
    store = get_store()
    return {"sessions": store.list_active()}


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


@router.post("/session/open")
def open_session(req: SessionOpenRequest, user: dict = Depends(get_current_user)):
    from core.session import Session
    from core.picker import next_task
    from app.agent import _task_view

    store = get_store()

    if req.status == "active":
        state = store.get(req.id)
        if state is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        session = Session.from_dict(state["session"])
        feedback_list = state.get("_feedback_list", [])
        session_id = req.id
        if user is not None and session.candidate != user["email"]:
            raise HTTPException(status_code=403, detail="Not your session.")
        if user is None and not session.candidate.startswith("guest-"):
            raise HTTPException(
                status_code=403,
                detail="Guests can only resume practice sessions. Log in to open this one.",
            )
    elif req.status == "completed":
        from core.storage import get_assessment, delete_assessment
        assessment = get_assessment(req.id)
        if assessment is None:
            raise HTTPException(status_code=404, detail="Assessment not found.")
        session_state = assessment.get("session")
        if session_state is None:
            raise HTTPException(status_code=400, detail="Assessment has no session data to restore.")
        session = Session.from_dict(session_state)
        if user is not None and session.candidate != user["email"]:
            raise HTTPException(status_code=403, detail="Not your assessment.")
        if user is None and not session.candidate.startswith("guest-"):
            raise HTTPException(
                status_code=403,
                detail="Guests can only resume practice sessions. Log in to open this one.",
            )
        session_id = store.create(session_state["candidate"])
        store.save(session_id, {"session": session_state})
        delete_assessment(req.id)
        feedback_list = []
    else:
        raise HTTPException(status_code=400, detail="status must be 'active' or 'completed'")

    # Resume an in-flight remediation task if one is pending (generated tasks
    # are excluded from the bank picker, so we surface them directly).
    task = next(
        (t for t in session.tasks if t.get("generated") and t["id"] not in session.asked_task_ids),
        None,
    ) or next_task(session)
    return {
        "session_id": session_id,
        "candidate": session.candidate,
        "mode": session.mode,
        "total_tasks": len(session.tasks),
        "task_index": session.index,
        "current_task": _task_view(task, session) if task else None,
        "results": feedback_list,
        "skill_states": {
            k: {"score": v.score, "confidence": v.confidence, "questions_answered": v.questions_answered}
            for k, v in session.skill_states.items()
        },
    }


@router.post("/start")
def start_assessment(req: StartRequest, user: dict = Depends(get_current_user)):
    from core.session import Session
    from core.picker import next_task
    from app.agent import _task_view
    from core.learner_bridge import LearnerBridge

    store = get_store()
    if user is not None:
        candidate = user["email"]
    else:
        candidate = f"guest-{uuid.uuid4().hex[:8]}"

    session_id = store.create(candidate)

    state = {}
    ctx = _FakeToolContext(state)

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

    ctx.state["session"] = session.to_dict()
    store.save(session_id, ctx.state)

    # Use the custom task directly if one was injected; otherwise let the picker decide.
    if custom_task:
        first_task = _task_view(custom_task, session)
    else:
        task = next_task(session)
        first_task = _task_view(task, session) if task else None

    # Bootstrap the learning-partner knowledge graph from the picked task.
    learner = None
    try:
        bridge = LearnerBridge()
        bridge.ensure_learner(candidate)
        if first_task is not None:
            boot = bridge.bootstrap_task(first_task)
            learner = {
                "learner_id": str(bridge.learner_id(candidate)),
                "primary_node_slug": boot.get("primary_node_slug"),
            }
    except Exception:
        # Never let MVP integration break session startup.
        learner = None

    return {
        "session_id": session_id,
        "candidate": session.candidate,
        "mode": session.mode,
        "message": f"Assessment started for {session.candidate}.",
        "total_tasks": len(session.tasks),
        "first_task": first_task,
        "learner": learner,
    }


@router.post("/submit")
def submit_answer(req: SubmitRequest, user: dict = Depends(get_current_user)):
    from core.session import Session, SkillState
    from core.picker import next_task as next_task_bank
    from core.score import bayesian_update, effective_score, measurement_variance
    from core.hints import hint_penalty
    from evaluators.judge import LLMJudge
    from app.agent import _task_view

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
        nxt = next_task_bank(session)
        return {
            "result": existing.to_dict(),
            "coach": existing.coach,
            "next_task": _task_view(nxt, session) if nxt else None,
            "remaining": len(session.tasks) - session.index,
            "note": "Already answered.",
        }

    result, coach = LLMJudge().evaluate(task, req.answer)

    skill_update = None

    if session.mode == "assessment":
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

        skill_update = {
            "skill": skill_id,
            "new_score": new_score,
            "new_confidence": session.get_skill_state(skill_id).confidence,
            "hints_used": viewed,
        }
    else:
        feedback_entry = {
            "task_id": task["id"],
            "prompt": task["prompt"],
            "type": "code",
            "skill": task["skill"],
            "user_answer": req.answer,
            "result": result.to_dict(),
            "feedback": coach.feedback,
            "coach": coach.to_dict(),
            "hints_used": [],
            "scored": False,
        }
        feedback_list.append(feedback_entry)

    session.asked_task_ids.add(req.task_id)
    session.index += 1

    # Feed the judge result into the learning-partner MVP (evidence -> state ->
    # frontier -> next action). Never allowed to break the response.
    learner_update = None
    try:
        from core.learner_bridge import LearnerBridge

        learner_update = LearnerBridge().record_submission(
            session.candidate, task, result, coach, viewed_hints=req.hints_used or []
        )
    except Exception:
        learner_update = None

    # Iterative remediation: if the learner model still has an actionable gap,
    # generate a simpler task for the highest-information-gain node and make it
    # the next question (overriding the bank picker). The generated task is
    # persisted in the session, so a later /submit for it records evidence.
    next_task = None
    if learner_update is not None:
        from core.remediation import plan_remediation

        snapshot = None
        try:
            snapshot = LearnerBridge().learner_snapshot(session.candidate)
        except Exception:
            snapshot = None

        generated = plan_remediation(
            session, task, result, learner_update, snapshot or {}
        )
        if generated is not None:
            next_task = _task_view(generated, session)

    if next_task is None:
        nxt = next_task_bank(session)
        next_task = _task_view(nxt, session) if nxt else None

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


@router.post("/report")
def get_report(req: ReportRequest, user: dict = Depends(get_current_user)):
    from core.session import Session
    from core.report import build_report
    from core.storage import save_assessment

    store = get_store()
    state = store.get(req.session_id)
    if state is None:
        raise HTTPException(status_code=400, detail="No active assessment.")

    session = Session.from_dict(state["session"])
    if session.mode == "practice":
        raise HTTPException(
            status_code=400,
            detail="Practice (anonymous) sessions have no report. Start an assessed session to get feedback.",
        )

    if user is not None and session.candidate != user["email"]:
        raise HTTPException(status_code=403, detail="Not your session.")

    report = build_report(session)
    report["assessment_id"] = save_assessment(session, report)

    # Attach the learning-partner learner snapshot (states, frontier,
    # misconceptions, next action). Non-fatal on any MVP error.
    try:
        from core.learner_bridge import LearnerBridge

        report["learner"] = LearnerBridge().learner_snapshot(session.candidate)
    except Exception:
        report["learner"] = None

    store.delete(req.session_id)

    return report


@router.get("/history")
def get_history(limit: int = 20):
    from core.storage import list_assessments
    return {"assessments": list_assessments(limit)}


@router.get("/sessions")
def list_sessions(user: dict = Depends(get_current_user)):
    store = get_store()
    from core.storage import list_assessments_by_candidate

    if user is None:
        return {"sessions": []}
    candidate = user["email"]

    active = store.list_by_candidate(candidate)
    completed = list_assessments_by_candidate(candidate)

    sessions = []
    for s in active:
        sessions.append({
            "id": s["session_id"],
            "candidate": s["candidate"],
            "status": "active",
            "updated_at": s["updated_at"],
            "score": None,
            "verdict": None,
        })
    for a in completed:
        sessions.append({
            "id": a["id"],
            "candidate": a["candidate"],
            "status": "completed",
            "updated_at": a["finished_at"],
            "score": a["overall_score"],
            "verdict": a["verdict"],
        })

    sessions.sort(key=lambda s: s["updated_at"], reverse=True)
    return {"sessions": sessions}


@router.get("/tasks")
def list_tasks():
    from core.config import load_yaml

    tasks = load_yaml("tasks.yaml")["tasks"]
    return {
        "tasks": [
            {
                "id": t["id"],
                "skill": t["skill"],
                "difficulty": t.get("difficulty", 2),
                "prompt": t["prompt"],
            }
            for t in tasks
        ]
    }


@router.delete("/sessions/active/{session_id}")
def delete_active_session(session_id: str, user: dict = Depends(get_current_user)):
    store = get_store()
    state = store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if user is not None:
        from core.session import Session
        sess = Session.from_dict(state["session"])
        if sess.candidate != user["email"]:
            raise HTTPException(status_code=403, detail="Not your session.")
    store.delete(session_id)
    return {"ok": True}


@router.delete("/assessments/{assessment_id}")
def delete_assessment_endpoint(assessment_id: str, user: dict = Depends(get_current_user)):
    from core.storage import delete_assessment, get_assessment
    if user is not None:
        assessment = get_assessment(assessment_id)
        if assessment is None:
            raise HTTPException(status_code=404, detail="Assessment not found.")
        from core.session import Session
        sess = Session.from_dict(assessment["session"])
        if sess.candidate != user["email"]:
            raise HTTPException(status_code=403, detail="Not your assessment.")
    if not delete_assessment(assessment_id):
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return {"ok": True}


@router.delete("/sessions/clear/{candidate}")
def clear_candidate_data(candidate: str, user: dict = Depends(get_current_user)):
    store = get_store()
    from core.storage import delete_assessments_by_candidate, get_learner_binding, delete_learner_binding
    from core.learner_bridge import clear_learner_data
    if user is not None:
        candidate = user["email"]
    active_deleted = store.delete_by_candidate(candidate)
    assessments_deleted = delete_assessments_by_candidate(candidate)
    learner_deleted = 0
    learner_id = get_learner_binding(candidate)
    if learner_id:
        learner_deleted = clear_learner_data(learner_id)
        delete_learner_binding(candidate)
    return {
        "ok": True,
        "deleted": active_deleted + assessments_deleted + learner_deleted,
    }