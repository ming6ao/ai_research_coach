"""v1 session resources: canonical REST replacement for /api/start, /submit,
/complete, /session/open, /sessions, /sessions/active/{id}.

Shapes (all wrapped in ``{"data": ...}``):
- POST   /api/v1/sessions            -> 201 {id, candidate, total_tasks, task_index, current_task}
- GET    /api/v1/sessions/{id}       -> {id, candidate, total_tasks, task_index, current_task, results, ability}
- DELETE /api/v1/sessions/{id}       -> 204
- POST   /api/v1/sessions/{id}/answers     {task_id, answer}
- POST   /api/v1/sessions/{id}/completion  {}

Trajectory data lives in ``session_steps`` (RL-shaped per-step rows); the
``active_sessions`` row holds only the compact live state.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.auth import get_current_user
from backend.dependencies import get_store, resolve_candidate
from backend.v1.schemas import AnswerSubmitRequest, SessionCreateRequest

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
    """Read-time shrunk mastery block (global + nested domain/area/skill)."""
    from coach.area_score import AreaState, area_report_dict

    ability = session.get_ability()
    global_state = AreaState(
        mean=ability.score,
        variance=ability.variance,
        questions_answered=ability.questions_answered,
    )
    return area_report_dict(global_state, session.node_states)


def _save_area_beliefs(session) -> None:
    """Persist per-node sufficient statistics (best-effort)."""
    try:
        from coach.tasks import save_area_belief
        from coach.taxonomy import NODE_LEVEL

        level_names = {1: "domain", 2: "area", 3: "skill"}
        for node, st in session.node_states.items():
            level = level_names.get(NODE_LEVEL.get(node, 0))
            if not level:
                continue
            save_area_belief(
                session.candidate, level, node, st.mean, st.variance, st.questions_answered
            )
    except Exception:
        pass


def _update_beliefs(session, task, targets, result, observation, global_difficulty):
    """Apply one scored observation: global ability once + per-target nodes.

    Each scored part's primary leaf skill updates that skill, its area, its
    domain (every ancestor), at the part's own difficulty. Returns
    ``(before, after, new_score, new_variance, new_questions)``.
    """
    from coach.score import bayesian_update, effective_score, measurement_variance
    from coach.session import SkillState
    from coach.steps import belief_state
    from coach.taxonomy import ancestors

    state_obj = session.get_ability()
    session.ensure_area_beliefs()
    before = belief_state(session)

    obs_variance = measurement_variance(global_difficulty, state_obj.score)
    new_score, new_variance = bayesian_update(
        state_obj.score, state_obj.variance, observation, obs_variance
    )
    session.ability = SkillState(
        score=new_score,
        variance=new_variance,
        questions_answered=state_obj.questions_answered + 1,
        evidence=state_obj.evidence + [result.rationale],
    )

    scored_by_key = {p["key"]: p for p in (result.parts or [])}
    for part in targets:
        part_max = int(part.get("max_score") or 5)
        part_score = scored_by_key.get(part["key"], {}).get("score") or part_max * 0.5
        part_obs = effective_score(part_score / part_max if part_max else 0.0)
        part_tags = part.get("tags") or {}
        primary_tag = part_tags.get("primary")
        part_difficulty = int(part.get("difficulty") or task.get("difficulty") or 1)
        if primary_tag:
            for node in [primary_tag, *ancestors(primary_tag)]:
                st = session.get_node_state(node)
                session.node_states[node] = st.update(part_difficulty, part_obs)

    after = belief_state(session)
    return before, after, new_score, new_variance, state_obj.questions_answered + 1


def _persist_beliefs(session, new_score, new_variance, new_questions) -> None:
    """Persist global + per-area beliefs (best-effort)."""
    try:
        from coach.tasks import save_skill_belief as _save_belief

        _save_belief(session.candidate, new_score, new_variance, new_questions)
        _save_area_beliefs(session)
    except Exception:
        pass


def _latest_task_step(session_id: str, task_id: str):
    """Latest recorded step for a task in a session, or None."""
    from coach.steps import list_steps

    steps = [
        s for s in list_steps(session_id)
        if (s.get("task_id") or (s.get("task_snapshot") or {}).get("id")) == task_id
    ]
    return steps[-1] if steps else None


def _last_code_for(session_id: str, task_id: str):
    """Candidate's latest submitted code for a task (phase carry-forward)."""
    try:
        from coach.steps import answer_for_task

        return answer_for_task(session_id, task_id)
    except Exception:
        return None


def _replay_response(session, session_id: str, step: dict) -> dict:
    """Stored-result response for an idempotent re-submit."""
    from coach.selection import pick_next_task

    return {
        "data": {
            "result": step.get("result") or {},
            "coach": step.get("coaching") or {},
            "next_task": pick_next_task(session.candidate, session, session_id=session_id),
            "remaining": len(session.tasks) - session.index,
            "ability_update": None,
            "mastery": _mastery_dict(session),
            "already_answered": True,
        }
    }


def _load_session(store, session_id: str):
    """Load a session, hydrate its results from steps, and return (session, state)."""
    from coach.session import Session
    from coach.steps import list_steps

    state = store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    session = Session.from_dict(state["session"])
    for st in list_steps(session_id):
        try:
            from coach.judge import EvaluationResult

            session.results.append(EvaluationResult.from_dict(st.get("result") or {}))
        except Exception:
            pass
    return session, state


_COMBINED_CACHE: dict[str, tuple[str, Optional[dict]]] = {}
_COMBINED_CACHE_MAX = 1000


def _describe_and_categorize(prompt: str) -> tuple[str, Optional[dict]]:
    """One combined context-notes + tag-categorization call per prompt.

    The result is cached per request so ``_describe_context`` and
    ``_categorize_tags`` never trigger a second LLM round-trip for the same
    task. ``tags`` is ``None`` when categorization could not be resolved.
    """
    key = (prompt or "").strip()
    if key in _COMBINED_CACHE:
        return _COMBINED_CACHE[key]
    notes: str = ""
    tags: Optional[dict] = None
    try:
        from coach.task_decomposer import TaskDecomposer

        out = TaskDecomposer().describe_and_categorize(prompt)
        notes = out.get("context_notes") or ""
        tags = out.get("tags") or None
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
    """Explicit tags win; otherwise one best-effort LLM categorization.

    Raises ``HTTPException(422)`` when categorization cannot determine a valid
    primary leaf skill — an uncategorized task must not be created.
    """
    if explicit is not None:
        return explicit
    _notes, tags = _describe_and_categorize(prompt)
    if not tags or not tags.get("primary"):
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not categorize this question into the taxonomy. "
                "Provide tags.primary (a leaf skill) explicitly, or retry."
            ),
        )
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

    node: Optional[str] = None
    raw_node = (req.node or "").strip()
    if raw_node:
        from coach.taxonomy import resolve_node

        node = resolve_node(raw_node)
        if node is None:
            from coach.taxonomy import ALL_NODES

            raise HTTPException(
                status_code=422,
                detail=f"Unknown taxonomy node '{raw_node}'. Expected one of: {', '.join(ALL_NODES)}.",
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
        from coach.tasks import single_part

        prompt = req.initial_question.strip()
        tags = _categorize_tags(prompt)
        custom_task = _create_task(
            owner=candidate,
            parts=[single_part(prompt, tags=tags, max_score=5, difficulty=2)],
            source="user",
            is_public=is_guest,
            context_notes=_describe_context(prompt),
            tags=tags,
        )
        session.tasks.insert(0, custom_task)

    if custom_task:
        first_task = task_view(custom_task, session)
    elif node:
        first_task = pick_next_task(
            candidate, session, node=node, sample_top_n=RANDOM_FIRST_TOP_N
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
    from coach.steps import feedback_from_steps, list_steps

    store = get_store()
    session, _state = _load_session(store, session_id)
    _check_owner(session, user, guest_ok=True)
    if user is None and not session.candidate.startswith("guest-"):
        raise HTTPException(
            status_code=403,
            detail="Guests can only open their own sessions. Log in to open this one.",
        )
    task = pick_next_task(session.candidate, session, session_id=session_id)
    steps = list_steps(session_id)
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
    from coach.config import PHASE_MAX_ATTEMPTS, default_pass_score
    from coach.judge import LLMJudge
    from coach.score import effective_score
    from coach.selection import pick_next_task
    from coach.session import active_phase, completed_phases, effective_parts, task_view
    from coach.steps import insert_step

    store = get_store()
    session, _state = _load_session(store, session_id)
    _check_owner(session, user)

    task = next((t for t in session.tasks if t["id"] == req.task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {req.task_id} not found.")

    # Idempotency: replay only an identical answer to the current
    # (unadvanced) step.
    active = active_phase(task, session)
    if active is None:
        latest = _latest_task_step(session_id, task["id"])
        if latest is not None:
            return _replay_response(session, session_id, latest)
        raise HTTPException(status_code=400, detail="This task is already complete.")
    latest = _latest_task_step(session_id, task["id"])
    latest_parts = (latest.get("result") or {}).get("parts") or [] if latest else []
    if (
        latest is not None
        and latest.get("user_answer") == req.answer
        and latest_parts
        and latest_parts[0].get("key") == active["key"]
    ):
        return _replay_response(session, session_id, latest)

    # Every task is step-by-step: score only the active step, judged against
    # the candidate's previous code for the same task.
    parts = effective_parts(task)
    idx = completed_phases(task, session)
    active = parts[idx]
    pass_score = int(
        active.get("pass_score") or default_pass_score(int(active.get("max_score") or 5))
    )
    previous_code = _last_code_for(session_id, task["id"])
    judge_task = {
        **task,
        "parts": [active],
        "max_score": int(active.get("max_score") or 5),
        "difficulty": int(active.get("difficulty") or task.get("difficulty") or 2),
    }
    targets = [active]
    global_difficulty = int(active.get("difficulty") or task.get("difficulty") or 2)
    role = (
        str(task.get("generated_kind") or "remediate")
        if task.get("generated")
        else "bank"
    )

    result, coach = LLMJudge().evaluate(judge_task, req.answer, previous_code=previous_code)

    observation = effective_score(result.fraction)
    before, after, new_score, new_variance, new_questions = _update_beliefs(
        session, task, targets, result, observation, global_difficulty
    )

    step_index = session.submission_index
    attempts = session.phase_attempts.get(task["id"], 0) + 1
    passed = result.score >= pass_score
    advanced = passed or attempts >= PHASE_MAX_ATTEMPTS
    if advanced:
        session.task_progress[task["id"]] = idx + 1
        session.phase_attempts[task["id"]] = 0
        if session.task_progress[task["id"]] >= len(parts):
            session.asked_task_ids.add(task["id"])
            session.index += 1
    else:
        session.phase_attempts[task["id"]] = attempts
    session.results.append(result)

    insert_step(
        session_id,
        session.candidate,
        step_index,
        task,
        role,
        req.answer,
        result.score,
        result.max_score,
        result.fraction,
        observation,
        before,
        after,
        result.to_dict(),
        coach.to_dict(),
    )
    session.submission_index += 1

    _persist_beliefs(session, new_score, new_variance, new_questions)

    ability_update = {
        "new_score": new_score,
        "new_confidence": session.get_ability().confidence,
    }

    try:
        next_task = pick_next_task(
            session.candidate, session,
            last_submission={
                "task": task,
                "answer": req.answer,
                "result": result,
                "coach": coach,
            },
            session_id=session_id,
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