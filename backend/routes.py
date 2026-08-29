"""API routes wrapping the agent's tool functions."""

import sys
import json
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from backend.dependencies import get_store

router = APIRouter(prefix="/api", tags=["assessment"])


class StartRequest(BaseModel):
    candidate_name: str
    target_role: str


class SubmitRequest(BaseModel):
    session_id: str
    task_id: str
    answer: str


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


@router.post("/session/open")
def open_session(req: SessionOpenRequest):
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
    elif req.status == "completed":
        from core.storage import get_assessment, delete_assessment
        assessment = get_assessment(req.id)
        if assessment is None:
            raise HTTPException(status_code=404, detail="Assessment not found.")
        session_state = assessment.get("session")
        if session_state is None:
            raise HTTPException(status_code=400, detail="Assessment has no session data to restore.")
        session_id = store.create(session_state["candidate"], session_state["role"])
        store.save(session_id, {"session": session_state})
        delete_assessment(req.id)
        session = Session.from_dict(session_state)
        feedback_list = []
    else:
        raise HTTPException(status_code=400, detail="status must be 'active' or 'completed'")

    task = next_task(session)
    return {
        "session_id": session_id,
        "candidate": session.candidate,
        "role": session.role,
        "role_name": session.role_cfg["name"],
        "total_tasks": len(session.tasks),
        "task_index": session.index,
        "current_task": _task_view(task) if task else None,
        "results": feedback_list,
        "skill_states": {
            k: {"score": v.score, "confidence": v.confidence, "questions_answered": v.questions_answered}
            for k, v in session.skill_states.items()
        },
    }


@router.post("/start")
def start_assessment(req: StartRequest):
    from core.session import Session
    from core.picker import next_task
    from app.agent import _task_view

    store = get_store()
    session_id = store.create(req.candidate_name, req.target_role)

    state = {}
    ctx = _FakeToolContext(state)

    try:
        session = Session(req.candidate_name, req.target_role)
    except ValueError as e:
        store.delete(session_id)
        raise HTTPException(status_code=400, detail=str(e))

    ctx.state["session"] = session.to_dict()
    store.save(session_id, ctx.state)

    task = next_task(session)
    first_task = _task_view(task) if task else None

    return {
        "session_id": session_id,
        "message": f"Assessment started for {session.role_cfg['name']}.",
        "total_tasks": len(session.tasks),
        "first_task": first_task,
        "role_name": session.role_cfg["name"],
    }


@router.post("/submit")
def submit_answer(req: SubmitRequest):
    from core.session import Session, SkillState
    from core.picker import next_task
    from core.score import update_skill_score
    from evaluators.judge import LLMJudge
    from app.agent import _task_view

    store = get_store()
    state = store.get(req.session_id)
    if state is None:
        raise HTTPException(status_code=400, detail="No active assessment.")

    session = Session.from_dict(state["session"])
    feedback_list = state.get("_feedback_list", [])

    task = next((t for t in session.tasks if t["id"] == req.task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {req.task_id} not found.")

    existing = next((r for r in session.results if r.task_id == req.task_id), None)
    if existing is not None:
        nxt = next_task(session)
        return {
            "result": existing.to_dict(),
            "next_task": _task_view(nxt) if nxt else None,
            "remaining": len(session.tasks) - session.index,
            "note": "Already answered.",
        }

    result, feedback = LLMJudge().evaluate(task, req.answer)

    skill_id = task["skill"]
    state_obj = session.get_skill_state(skill_id)
    normalized_score = result.fraction

    new_score, new_confidence = update_skill_score(
        state_obj.score, state_obj.confidence, normalized_score,
    )

    session.skill_states[skill_id] = SkillState(
        score=new_score,
        confidence=new_confidence,
        questions_answered=state_obj.questions_answered + 1,
        evidence=state_obj.evidence + [result.rationale],
    )

    session.asked_task_ids.add(req.task_id)
    session.results.append(result)
    session.index += 1

    feedback_entry = {
        "task_id": task["id"],
        "prompt": task["prompt"],
        "type": "code",
        "skill": task["skill"],
        "user_answer": req.answer,
        "result": result.to_dict(),
        "feedback": feedback,
    }
    feedback_list.append(feedback_entry)

    state["session"] = session.to_dict()
    store.save(req.session_id, state, feedback_list)

    nxt = next_task(session)

    return {
        "result": result.to_dict(),
        "feedback": feedback,
        "next_task": _task_view(nxt) if nxt else None,
        "remaining": len(session.tasks) - session.index,
        "skill_update": {
            "skill": skill_id,
            "new_score": new_score,
            "new_confidence": new_confidence,
        },
    }


@router.post("/report")
def get_report(req: ReportRequest):
    from core.session import Session
    from core.report import build_report
    from core.storage import save_assessment

    store = get_store()
    state = store.get(req.session_id)
    if state is None:
        raise HTTPException(status_code=400, detail="No active assessment.")

    session = Session.from_dict(state["session"])
    report = build_report(session)
    report["assessment_id"] = save_assessment(session, report)

    store.delete(req.session_id)

    return report


@router.get("/history")
def get_history(limit: int = 20):
    from core.storage import list_assessments
    return {"assessments": list_assessments(limit)}


@router.get("/sessions")
def list_sessions(candidate: str):
    store = get_store()
    from core.storage import list_assessments_by_candidate

    active = store.list_by_candidate(candidate)
    completed = list_assessments_by_candidate(candidate)

    sessions = []
    for s in active:
        sessions.append({
            "id": s["session_id"],
            "candidate": s["candidate"],
            "role": s["role"],
            "status": "active",
            "updated_at": s["updated_at"],
            "score": None,
            "verdict": None,
        })
    for a in completed:
        sessions.append({
            "id": a["id"],
            "candidate": a["candidate"],
            "role": a["role"],
            "status": "completed",
            "updated_at": a["finished_at"],
            "score": a["overall_score"],
            "verdict": a["verdict"],
        })

    sessions.sort(key=lambda s: s["updated_at"], reverse=True)
    return {"sessions": sessions}


@router.delete("/sessions/active/{session_id}")
def delete_active_session(session_id: str):
    store = get_store()
    state = store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    store.delete(session_id)
    return {"ok": True}


@router.delete("/assessments/{assessment_id}")
def delete_assessment_endpoint(assessment_id: str):
    from core.storage import delete_assessment
    if not delete_assessment(assessment_id):
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return {"ok": True}


@router.delete("/sessions/clear/{candidate}")
def clear_candidate_data(candidate: str):
    store = get_store()
    from core.storage import delete_assessments_by_candidate
    active_deleted = store.delete_by_candidate(candidate)
    assessments_deleted = delete_assessments_by_candidate(candidate)
    return {
        "ok": True,
        "deleted": active_deleted + assessments_deleted,
    }
