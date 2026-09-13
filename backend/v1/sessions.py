"""v1 session resources: canonical REST replacement for /api/start, /submit,
/complete, /session/open, /sessions, /sessions/active/{id}.

Shapes (all wrapped in ``{"data": ...}``):
- POST   /api/v1/sessions            -> 201 {id, candidate, total_tasks, task_index, current_task}
- GET    /api/v1/sessions/{id}       -> {id, candidate, total_tasks, task_index, current_task, results, ability}
- DELETE /api/v1/sessions/{id}       -> 204
- POST   /api/v1/sessions/{id}/answers     {task_id, answer, hints_used?}
- POST   /api/v1/sessions/{id}/completion  {}
- POST   /api/v1/sessions/{id}/share       {step_index?}  -> {token, url}
- POST   /api/v1/sessions/{id}/redo        {step_index, answer, hints_used?}

Trajectory data lives in ``session_steps`` (RL-shaped per-step rows); the
``active_sessions`` row holds only the compact live state. Shares / resume
follow the Copy-on-Write design (docs/collaboration-design.md).
"""

import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.auth import get_current_user
from backend.dependencies import get_store, resolve_candidate
from backend.v1.schemas import AnswerSubmitRequest, RedoRequest, SessionCreateRequest, ShareRequest

router = APIRouter(prefix="/sessions", tags=["v1:sessions"])

# "Random question" samples uniformly from the top-N EIG bank candidates.
RANDOM_FIRST_TOP_N = 5


def _candidate_for(user: Optional[dict], request) -> str:
    """Stable identity: signed-in email or per-browser guest id."""
    return resolve_candidate(user, request)


def _ability_dict(session) -> dict:
    ability = session.get_ability()
    return {
        "score": ability.score,
        "confidence": ability.confidence,
        "questions_answered": ability.questions_answered,
    }


def _mastery_dict(session) -> dict:
    """Read-time shrunk mastery block (global + families + tags)."""
    from coach.area_score import AreaState, area_report_dict

    ability = session.get_ability()
    global_state = AreaState(
        mean=ability.score,
        variance=ability.variance,
        questions_answered=ability.questions_answered,
    )
    return area_report_dict(global_state, session.family_states, session.tag_states)


def _save_area_beliefs(session) -> None:
    """Persist per-family and per-tag sufficient statistics (best-effort)."""
    try:
        from coach.tasks import save_area_belief

        for fam, st in session.family_states.items():
            save_area_belief(
                session.candidate, "family", fam, st.mean, st.variance, st.questions_answered
            )
        for tag, st in session.tag_states.items():
            save_area_belief(
                session.candidate, "tag", tag, st.mean, st.variance, st.questions_answered
            )
    except Exception:
        pass


def _load_session(store, session_id: str):
    """Load a session, hydrate its results from steps, and return (session, state)."""
    from coach.session import Session
    from coach.shares import effective_steps

    state = store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    session = Session.from_dict(state["session"])
    for st in effective_steps(session_id, state):
        try:
            from coach.judge import EvaluationResult

            session.results.append(EvaluationResult.from_dict(st.get("result") or {}))
        except Exception:
            pass
    return session, state


def _materialize_prefix(session, session_id: str, state: dict) -> bool:
    """CoW fork: materialize a resumed session's share prefix as inherited steps.

    Returns True when a prefix was materialized (the session is now
    self-contained); False when the session was not resumed / already forked.
    """
    from coach.judge import EvaluationResult
    from coach.shares import get_share
    from coach.steps import insert_step

    token = state.get("_resumed_from_share")
    if not token:
        return False
    share = get_share(token)
    if share is None:
        return False
    steps = share["snapshot"].get("steps", [])
    for i, st in enumerate(steps):
        insert_step(
            session_id,
            session.candidate,
            i,
            st.get("task_snapshot") or {},
            st.get("role") or "bank",
            st.get("user_answer") or "",
            st.get("score") or 0.0,
            st.get("max_score") or 5.0,
            st.get("fraction") or 0.0,
            st.get("reward") or 0.0,
            st.get("hints_used") or [],
            st.get("state_before") or {},
            st.get("state_after") or {},
            st.get("result") or {},
            st.get("coaching") or {},
            inherited=True,
        )
    for st in steps:
        try:
            session.results.append(EvaluationResult.from_dict(st.get("result") or {}))
        except Exception:
            pass
    get_store().set_resumed_from_share(session_id, None)
    return True


_COMBINED_CACHE: dict[str, tuple[str, dict]] = {}
_COMBINED_CACHE_MAX = 1000


def _describe_and_categorize(prompt: str) -> tuple[str, dict]:
    """One combined context-notes + tag-categorization call per prompt.

    The result is cached per request so ``_describe_context`` and
    ``_categorize_tags`` never trigger a second LLM round-trip for the same
    task (§6: task creation uses a single Gemini call).
    """
    key = (prompt or "").strip()
    if key in _COMBINED_CACHE:
        return _COMBINED_CACHE[key]
    notes = ""
    tags = {"primary": "python", "secondary": []}
    try:
        from coach.task_decomposer import TaskDecomposer

        out = TaskDecomposer().describe_and_categorize(prompt)
        notes = out.get("context_notes") or ""
        tags = out.get("tags") or tags
    except Exception:
        pass
    if len(_COMBINED_CACHE) >= _COMBINED_CACHE_MAX:
        _COMBINED_CACHE.clear()
    _COMBINED_CACHE[key] = (notes, tags)
    return _COMBINED_CACHE[key]


def _describe_context(prompt: str, explicit: Optional[str] = None) -> str:
    """Author-supplied notes win; otherwise one best-effort LLM description."""
    if explicit is not None and explicit.strip():
        return explicit.strip()[:2000]
    notes, _tags = _describe_and_categorize(prompt)
    return notes


def _categorize_tags(prompt: str, explicit: Optional[dict] = None) -> dict:
    """Explicit tags win; otherwise one best-effort LLM categorization."""
    if explicit is not None:
        return explicit
    _notes, tags = _describe_and_categorize(prompt)
    return tags


def _session_view(session_id: str, session, current_task, feedback_list=None) -> dict:
    view = {
        "id": session_id,
        "candidate": session.candidate,
        "total_tasks": len(session.tasks),
        "task_index": session.index,
        "current_task": current_task,
    }
    if feedback_list is not None:
        view["results"] = feedback_list
        view["ability"] = _ability_dict(session)
        view["mastery"] = _mastery_dict(session)
    return view


def _check_owner(session, user: Optional[dict], guest_ok: bool = False) -> None:
    if user is not None and session.candidate != user["email"]:
        raise HTTPException(status_code=403, detail="Not your session.")
    if user is None and not guest_ok and not session.candidate.startswith("guest-"):
        raise HTTPException(
            status_code=403,
            detail="Guests can only open their own sessions. Log in to open this one.",
        )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Start coaching session")
def create_session(
    req: SessionCreateRequest,
    user: Optional[dict] = Depends(get_current_user),
    request: Request = None,
):
    from coach.selection import pick_next_task
    from coach.session import Session, task_view

    store = get_store()
    candidate = _candidate_for(user, request)
    is_guest = candidate.startswith("guest-")

    family: Optional[str] = None
    if req.family:
        from coach.taxonomy import FAMILIES

        family = (req.family or "").strip()
        if family not in FAMILIES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown family '{family}'. Expected one of: {', '.join(FAMILIES)}.",
            )

    session_id = store.create(candidate)
    scoped_tasks = None
    if req.task_ids:
        from coach.tasks import get_task as _get_task

        scoped_tasks = [t for tid in req.task_ids if (t := _get_task(tid))]
    session = Session(candidate, tasks=scoped_tasks or [])

    custom_task = None
    if req.initial_question and req.initial_question.strip():
        from coach.tasks import create_task as _create_task

        prompt = req.initial_question.strip()
        tags = _categorize_tags(prompt)
        custom_task = _create_task(
            prompt=prompt,
            owner=candidate,
            difficulty=2,
            max_score=5,
            hints=[],
            source="user",
            is_public=is_guest,
            context_notes=_describe_context(prompt),
            tags=tags,
        )
        session.tasks.insert(0, custom_task)

    if custom_task:
        first_task = task_view(custom_task, session)
    elif req.family:
        first_task = pick_next_task(
            candidate, session, family=family, sample_top_n=RANDOM_FIRST_TOP_N
        )
        if first_task is None:
            first_task = pick_next_task(candidate, session)
    elif req.random_first:
        first_task = pick_next_task(candidate, session, sample_top_n=RANDOM_FIRST_TOP_N)
    else:
        first_task = pick_next_task(candidate, session)

    store.save(session_id, {"session": session.to_dict()})
    return {"data": _session_view(session_id, session, first_task)}


@router.get("/{session_id}", summary="Get session with current task")
def get_session(session_id: str, user: Optional[dict] = Depends(get_current_user)):
    from coach.selection import pick_next_task
    from coach.shares import effective_steps, feedback_from_steps

    store = get_store()
    session, state = _load_session(store, session_id)
    _check_owner(session, user, guest_ok=True)
    if user is None and not session.candidate.startswith("guest-"):
        raise HTTPException(
            status_code=403,
            detail="Guests can only open their own sessions. Log in to open this one.",
        )
    task = pick_next_task(session.candidate, session)
    steps = effective_steps(session_id, state)
    return {
        "data": _session_view(
            session_id, session, task, feedback_from_steps(steps)
        )
    }


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete session")
def delete_session(session_id: str, user: Optional[dict] = Depends(get_current_user)):
    from coach.session import Session

    store = get_store()
    state = store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if user is not None:
        sess = Session.from_dict(state["session"])
        if sess.candidate != user["email"]:
            raise HTTPException(status_code=403, detail="Not your session.")
    store.delete(session_id)
    return None


@router.post("/{session_id}/answers", summary="Submit answer for a task")
def submit_answer(
    session_id: str, req: AnswerSubmitRequest, user: Optional[dict] = Depends(get_current_user)
):
    from coach.hints import hint_penalty
    from coach.judge import LLMJudge
    from coach.score import bayesian_update, effective_score, measurement_variance
    from coach.selection import pick_next_task
    from coach.session import SkillState, task_view
    from coach.steps import belief_state, insert_step
    from coach.taxonomy import family_of

    store = get_store()
    session, state = _load_session(store, session_id)
    _check_owner(session, user)

    _materialize_prefix(session, session_id, state)

    task = next((t for t in session.tasks if t["id"] == req.task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {req.task_id} not found.")

    if req.task_id in session.asked_task_ids:
        existing = next((r for r in session.results if r.task_id == req.task_id), None)
        if existing is not None:
            from coach.shares import feedback_from_steps

            steps = []
            try:
                from coach.steps import list_steps

                steps = list_steps(session_id)
            except Exception:
                pass
            return {
                "data": {
                    "result": existing.to_dict(),
                    "coach": existing.coach,
                    "next_task": pick_next_task(session.candidate, session),
                    "remaining": len(session.tasks) - session.index,
                    "ability_update": None,
                    "mastery": _mastery_dict(session),
                    "already_answered": True,
                }
            }

    result, coach = LLMJudge().evaluate(task, req.answer)

    requested = session.viewed_hints.get(req.task_id, [])
    viewed = list(dict.fromkeys(list(req.hints_used or []) + requested))
    session.viewed_hints[req.task_id] = viewed

    state_obj = session.get_ability()
    session.ensure_area_beliefs()
    before = belief_state(session)

    penalty = hint_penalty(task, viewed)
    observation = effective_score(result.fraction, penalty)
    obs_variance = measurement_variance(task.get("difficulty", 1), state_obj.score)
    new_score, new_variance = bayesian_update(
        state_obj.score, state_obj.variance, observation, obs_variance
    )

    session.ability = SkillState(
        score=new_score,
        variance=new_variance,
        questions_answered=state_obj.questions_answered + 1,
        evidence=state_obj.evidence + [result.rationale],
        hints_used=state_obj.hints_used + viewed,
    )

    # Per-area updates: one answer updates exactly the primary tag, its
    # family, and the global belief (§4.2). Secondary tags never feed the
    # estimator (coverage/diversity only).
    task_tags = task.get("tags") or {}
    primary_tag = task_tags.get("primary")
    family = family_of(primary_tag) if primary_tag else None
    difficulty = task.get("difficulty", 1)
    if primary_tag:
        tag_state = session.get_tag_state(primary_tag)
        session.tag_states[primary_tag] = tag_state.update(difficulty, observation)
    if family:
        fam_state = session.get_family_state(family)
        session.family_states[family] = fam_state.update(difficulty, observation)

    after = belief_state(session)

    role = "bank"
    if task.get("generated"):
        role = str(task.get("generated_kind") or "remediate")
    insert_step(
        session_id,
        session.candidate,
        session.index,
        task,
        role,
        req.answer,
        result.score,
        result.max_score,
        result.fraction,
        observation,
        viewed,
        before,
        after,
        result.to_dict(),
        coach.to_dict(),
        inherited=False,
    )

    try:
        from coach.tasks import save_skill_belief as _save_belief

        _save_belief(
            session.candidate, new_score, new_variance,
            state_obj.questions_answered + 1,
        )
        _save_area_beliefs(session)
    except Exception:
        pass

    session.asked_task_ids.add(req.task_id)
    session.results.append(result)
    session.index += 1

    ability_update = {
        "new_score": new_score,
        "new_confidence": session.get_ability().confidence,
        "hints_used": viewed,
    }

    try:
        next_task = pick_next_task(
            session.candidate, session,
            last_submission={"task": task, "result": result, "coach": coach},
        )
    except Exception:
        from coach.picker import next_task as next_task_bank

        nxt = next_task_bank(session)
        next_task = task_view(nxt, session) if nxt else None

    store.save(session_id, {"session": session.to_dict()})

    return {
        "data": {
            "result": result.to_dict(),
            "coach": coach.to_dict(),
            "next_task": next_task,
            "remaining": len(session.tasks) - session.index,
            "ability_update": ability_update,
            "mastery": _mastery_dict(session),
            "already_answered": False,
        }
    }


@router.post("/{session_id}/completion", summary="Complete session")
def complete_session(session_id: str, user: Optional[dict] = Depends(get_current_user)):
    from coach.session import Session

    store = get_store()
    session, _state = _load_session(store, session_id)
    _check_owner(session, user)
    # The row stays in active_sessions for history/resume; "done" is derived
    # from the session JSON (pick_next_task returns None).
    return {
        "data": {
            "done": True,
            "ability": _ability_dict(session),
            "mastery": _mastery_dict(session),
        }
    }


@router.post("/{session_id}/share", summary="Share a trajectory prefix")
def share_session(
    session_id: str,
    req: ShareRequest,
    user: Optional[dict] = Depends(get_current_user),
):
    from coach.session import Session
    from coach.shares import build_share_snapshot, create_share, effective_steps

    store = get_store()
    session, state = _load_session(store, session_id)
    _check_owner(session, user)
    session.ensure_area_beliefs()

    steps = effective_steps(session_id, state)
    boundary = len(steps)
    if req.step_index is not None:
        boundary = max(0, min(int(req.step_index), len(steps)))
    prefix = steps[:boundary]

    snapshot = build_share_snapshot(session, prefix)
    token = create_share(session_id, boundary, snapshot, session.candidate)

    frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")
    url = f"{frontend_url}/shared/{token}"
    return {"data": {"token": token, "url": url, "step_index": boundary}}


@router.post("/{session_id}/redo", summary="Redo a shared prefix step (CoW fork)")
def redo_step(
    session_id: str,
    req: RedoRequest,
    user: Optional[dict] = Depends(get_current_user),
):
    from coach.hints import hint_penalty
    from coach.judge import LLMJudge
    from coach.score import bayesian_update, effective_score, measurement_variance
    from coach.selection import pick_next_task
    from coach.session import Session, SkillState
    from coach.shares import get_share
    from coach.steps import belief_state, insert_step
    from coach.taxonomy import family_of

    store = get_store()
    session, state = _load_session(store, session_id)
    _check_owner(session, user)

    token = state.get("_resumed_from_share")
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Only an unreforged shared prefix can be redone (continue or fork first).",
        )
    share = get_share(token)
    if share is None:
        raise HTTPException(status_code=404, detail="Share not found.")
    steps = share["snapshot"].get("steps", [])
    k = req.step_index
    if k < 0 or k >= len(steps):
        raise HTTPException(status_code=400, detail="step_index out of range.")

    # Materialize the prefix before the edited step as inherited history.
    for i, st in enumerate(steps):
        if i >= k:
            break
        insert_step(
            session_id,
            session.candidate,
            i,
            st.get("task_snapshot") or {},
            st.get("role") or "bank",
            st.get("user_answer") or "",
            st.get("score") or 0.0,
            st.get("max_score") or 5.0,
            st.get("fraction") or 0.0,
            st.get("reward") or 0.0,
            st.get("hints_used") or [],
            st.get("state_before") or {},
            st.get("state_after") or {},
            st.get("result") or {},
            st.get("coaching") or {},
            inherited=True,
        )

    task = steps[k].get("task_snapshot") or {}
    result, coach = LLMJudge().evaluate(task, req.answer)

    requested = session.viewed_hints.get(task.get("id"), [])
    viewed = list(dict.fromkeys(list(req.hints_used or []) + requested))
    session.viewed_hints[task.get("id")] = viewed

    state_obj = session.get_ability()
    session.ensure_area_beliefs()
    before = belief_state(session)

    penalty = hint_penalty(task, viewed)
    observation = effective_score(result.fraction, penalty)
    obs_variance = measurement_variance(task.get("difficulty", 1), state_obj.score)
    new_score, new_variance = bayesian_update(
        state_obj.score, state_obj.variance, observation, obs_variance
    )

    session.ability = SkillState(
        score=new_score,
        variance=new_variance,
        questions_answered=state_obj.questions_answered + 1,
        evidence=state_obj.evidence + [result.rationale],
        hints_used=state_obj.hints_used + viewed,
    )
    primary_tag = (task.get("tags") or {}).get("primary")
    family = family_of(primary_tag) if primary_tag else None
    difficulty = task.get("difficulty", 1)
    if primary_tag:
        tag_state = session.get_tag_state(primary_tag)
        session.tag_states[primary_tag] = tag_state.update(difficulty, observation)
    if family:
        fam_state = session.get_family_state(family)
        session.family_states[family] = fam_state.update(difficulty, observation)
    after = belief_state(session)

    insert_step(
        session_id,
        session.candidate,
        k,
        task,
        "redo",
        req.answer,
        result.score,
        result.max_score,
        result.fraction,
        observation,
        viewed,
        before,
        after,
        result.to_dict(),
        coach.to_dict(),
        inherited=False,
    )

    try:
        from coach.tasks import save_skill_belief as _save_belief

        _save_belief(
            session.candidate, new_score, new_variance,
            state_obj.questions_answered + 1,
        )
        _save_area_beliefs(session)
    except Exception:
        pass

    session.asked_task_ids.add(task.get("id"))
    session.index = k + 1
    session.results = [r for r in session.results if r.task_id != task.get("id")]
    session.results.append(result)
    store.set_resumed_from_share(session_id, None)

    try:
        next_task = pick_next_task(session.candidate, session)
    except Exception:
        next_task = None

    store.save(session_id, {"session": session.to_dict()})

    return {
        "data": {
            "result": result.to_dict(),
            "coach": coach.to_dict(),
            "next_task": next_task,
            "remaining": len(session.tasks) - session.index,
            "ability_update": {
                "new_score": new_score,
                "new_confidence": session.get_ability().confidence,
                "hints_used": viewed,
            },
            "mastery": _mastery_dict(session),
            "already_answered": False,
        }
    }