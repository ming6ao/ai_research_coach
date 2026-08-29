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


class ResumeRequest(BaseModel):
    session_id: str


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


@router.post("/session/resume")
def resume_session(req: ResumeRequest):
    from core.session import Session
    from core.picker import next_task
    from agent import _task_view

    store = get_store()
    state = store.get(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    session = Session.from_dict(state["session"])
    feedback_list = state.get("_feedback_list", [])

    task = next_task(session)
    return {
        "session_id": req.session_id,
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
    from agent import _task_view

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
    from core.feedback import generate_feedback
    from evaluators.registry import get_evaluator
    from judge.llm_judge import JudgeRetryableError
    from agent import _task_view

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

    try:
        result = get_evaluator(task["type"]).evaluate(task, req.answer)
    except JudgeRetryableError as e:
        raise HTTPException(status_code=503, detail=f"Transient evaluation failure: {e}")

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

    feedback = generate_feedback(task, req.answer, result.to_dict())

    feedback_entry = {
        "task_id": task["id"],
        "prompt": task["prompt"],
        "type": task["type"],
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
