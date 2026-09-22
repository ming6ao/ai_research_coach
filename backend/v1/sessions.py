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


def _last_language_for(session_id: str, task_id: str):
    """Language the candidate first answered a task in (locked), or None."""
    try:
        from coach.steps import list_steps

        for s in list_steps(session_id):
            tid = s.get("task_id") or (s.get("task_snapshot") or {}).get("id")
            if tid == task_id and s.get("language"):
                return s["language"]
        return None
    except Exception:
        return None


def _replay_response(session, session_id: str, step: dict) -> dict:
    """Stored-result response for an idempotent re-submit.

    Generation is disabled: replay is a read, so it must not mint a new task
    (an orphaned DB row / surprise LLM call on every repeat submit). It only
    surfaces a generated task already injected into the session.
    """
    from coach.selection import pick_next_task

    return {
        "data": {
            "result": step.get("result") or {},
            "coach": step.get("coaching") or {},
            "next_task": pick_next_task(
                session.candidate, session, session_id=session_id, allow_generation=False
            ),
            "remaining": len(session.tasks) - session.index,
            "ability_update": None,
            "mastery": _mastery_dict(session),
            "already_answered": True,
            "language": step.get("language") or None,
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

    The result is cached per request so ``_describe_context`` never triggers a
    second LLM round-trip for the same task. ``tags`` is ``None`` when
    categorization could not be resolved.
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
    from coach.session import Session

    store = get_store()
    candidate = _candidate_for(user, request)

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

    if node:
        # A node-directed start is bank-only: only serve a task whose primary
        # tag is under the requested node. Never mint a generated task here —
        # a node the bank can not serve simply has no question yet (the home
        # page hides such nodes), so a stale/direct request gets a clear 404
        # instead of an unrelated generated challenge.
        first_task = pick_next_task(
            candidate,
            session,
            node=node,
            sample_top_n=RANDOM_FIRST_TOP_N,
            allow_generation=False,
        )
        if first_task is None:
            raise HTTPException(
                status_code=404,
                detail=f"No questions available under '{node}' yet.",
            )
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
    # Resume is a read: never mint tasks here (allow_generation=False).
    # A task generated by the last submission is already in the session and
    # surfaces via the pending-generated branch.
    task = pick_next_task(
        session.candidate, session, session_id=session_id, allow_generation=False
    )
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

    # Every task is step-by-step: score only the active step.
    parts = effective_parts(task)
    idx = completed_phases(task, session)
    active = parts[idx]
    # Resolve the answer language: multi-language tasks take the candidate's
    # choice (defaulting to the first declared language), and the choice is
    # locked to the language of the task's first recorded answer.
    from coach.tasks import normalize_language

    languages = list(task.get("languages") or [task.get("language") or "python"])
    locked_language = _last_language_for(session_id, task["id"])
    if locked_language:
        chosen_language = normalize_language(locked_language)
    else:
        requested = normalize_language(req.language) if req.language else languages[0]
        chosen_language = requested if requested in languages else languages[0]
    judge_task = {
        **task,
        "language": chosen_language,
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

    result, coach = LLMJudge().evaluate(judge_task, req.answer)

    observation = effective_score(result.fraction)
    before, after, new_score, new_variance, new_questions = _update_beliefs(
        session, task, targets, result, observation, global_difficulty
    )

    step_index = session.submission_index
    # Delivery always shows the next step, regardless of the score: the
    # learner reviews the coaching for each step and moves on.
    session.task_progress[task["id"]] = idx + 1
    session.phase_attempts.pop(task["id"], None)
    if session.task_progress[task["id"]] >= len(parts):
        session.asked_task_ids.add(task["id"])
        session.index += 1
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
        language=chosen_language,
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
        next_task = task_view(nxt, session, session_id=session_id) if nxt else None

    # First persisted answer: mint an LLM title + summary so the home page can
    # label the session and preview it on hover. Draft sessions (no answer yet)
    # are staged in memory and never reach the database.
    title = summary = None
    if not store.is_persisted(session_id):
        try:
            from coach.task_decomposer import TaskDecomposer

            info = TaskDecomposer().describe_session(task, req.answer)
            title = info.get("title") or ""
            summary = info.get("summary") or ""
        except Exception:
            title = summary = ""

    store.save(
        session_id,
        {"session": session.to_dict()},
        persist=True,
        title=title,
        summary=summary,
    )

    return {
        "data": {
            "result": result.to_dict(),
            "coach": coach.to_dict(),
            "next_task": next_task,
            "remaining": len(session.tasks) - session.index,
            "ability_update": ability_update,
            "mastery": _mastery_dict(session),
            "already_answered": False,
            "language": chosen_language,
        }
    }


@router.post("/{session_id}/completion", summary="Complete session")
def complete_session(session_id: str, user: Optional[dict] = Depends(get_current_user)):
    from coach.session import Session

    store = get_store()
    session, _state = _load_session(store, session_id)
    _check_owner(session, user)
    # Mark the session finished so the home page can show it as done without
    # re-running the picker. The row stays in active_sessions for review/resume.
    store.set_status(session_id, "done")
    return {
        "data": {
            "done": True,
            "ability": _ability_dict(session),
            "mastery": _mastery_dict(session),
        }
    }