"""Next-task selection (graph-free hybrid, open-ended).

1. Pending generated task — an injected follow-up not yet asked surfaces first
   (generated tasks are excluded from the bank picker).
2. Active step task — a task that has been started but not completed
   continues (next step after a pass, or the same step after a failed
   attempt). Its view carries the candidate's prior code forward as
   ``previous_code``.
3. Judge-driven follow-up — after a submission, ``plan_followup`` may inject
   an adaptive drill (simpler on failure; harder escalation or sibling
   prerequisite pivot after a solved follow-up).
4. EIG bank picker — ``coach.picker.next_task(session)``.
5. Fresh challenge — when the bank is exhausted, mint an ability-matched
   task via ``plan_challenge`` so the session keeps going indefinitely.
   ``None`` is returned only when generation also fails; the session ends
   explicitly when the user chooses Finish / View progress.
"""

from __future__ import annotations

from typing import Optional

from coach.session import effective_parts, task_view


def _last_code_for(session_id: Optional[str], task_id: str) -> Optional[str]:
    """Fetch the candidate's latest submitted code for a task, or None."""
    if not session_id:
        return None
    try:
        from coach.steps import answer_for_task

        return answer_for_task(session_id, task_id)
    except Exception:
        return None


def _task_started(session, task: dict) -> bool:
    """True once a step task has at least one attempt or passed step."""
    task_id = task.get("id")
    return bool(
        session.task_progress.get(task_id, 0)
        or session.phase_attempts.get(task_id, 0)
    )


def _active_step_task(session, task: Optional[dict] = None) -> Optional[dict]:
    """A started-but-unfinished step task, or None.

    Called with the just-submitted task (post-submit path) or without one
    (resume path, where it scans the session's tasks).
    """
    def unfinished(t: dict) -> bool:
        parts = effective_parts(t)
        return (
            bool(parts)
            and t.get("id") not in session.asked_task_ids
            and session.task_progress.get(t.get("id"), 0) < len(parts)
            and _task_started(session, t)
        )

    if task is not None and unfinished(task):
        return task
    for t in getattr(session, "tasks", []) or []:
        if unfinished(t):
            return t
    return None


def pick_next_task(
    candidate: str,
    session,
    last_submission: Optional[dict] = None,
    sample_top_n: Optional[int] = None,
    node: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict | None:
    """Choose the next task to present.

    ``last_submission`` carries ``{"task", "answer", "result", "coach"}``
    from a just-recorded submission (``answer`` is the candidate's code,
    carried into the next step). ``sample_top_n`` (> 1) samples uniformly
    from the top-N EIG bank candidates instead of always taking the single
    best; it applies to the bank-picker branch only. ``node`` restricts the
    bank-picker branch to tasks in one domain/area/skill (used to seed a
    session with a question from an area); it never affects
    pending/follow-up branches. ``session_id`` lets the resume path fetch the
    candidate's prior code for an in-progress step task.
    """
    from coach.picker import next_task as next_task_bank

    # 1. Pending generated follow-up first. Only follow-ups injected into
    # *this* session count: a generated task that merely happens to sit in the
    # visible bank (persisted by an earlier session) must never resurface as
    # pending, and must never bypass the requested ``node`` scope.
    pending = next(
        (
            t
            for t in session.tasks
            if t.get("generated")
            and t["id"] in session.generated_task_ids
            and t["id"] not in session.asked_task_ids
        ),
        None,
    )
    if pending is not None:
        return task_view(pending, session)

    # 2. Continue / retry an active step task.
    active = _active_step_task(session, (last_submission or {}).get("task"))
    if active is not None:
        previous_code = None
        if last_submission and last_submission.get("answer"):
            previous_code = last_submission.get("answer")
        else:
            previous_code = _last_code_for(session_id, active["id"])
        return task_view(active, session, previous_code=previous_code)

    # 3. Judge-driven follow-up after a submission (LLM drill/escalate/pivot).
    if last_submission is not None:
        from coach.remediation import plan_followup

        generated = plan_followup(
            session,
            last_submission.get("task"),
            last_submission.get("result"),
            last_submission.get("coach"),
        )
        if generated is not None:
            return task_view(generated, session)

    # 4. EIG bank picker.
    nxt = next_task_bank(session, sample_top_n=sample_top_n, node=node)
    if nxt is not None:
        return task_view(nxt, session)

    # 5. Bank exhausted -> mint a fresh adaptive challenge so the session
    # keeps going indefinitely (user exits explicitly via Finish). Steer it
    # toward the least-covered skill so scope keeps widening.
    try:
        from coach.remediation import least_covered, plan_challenge

        # Stay inside the requested node: mint the challenge under the
        # least-covered leaf in that subtree, not the globally least-covered
        # skill (which would hand an unrelated question to a node request).
        prefer_node = least_covered(session, node)
        challenge = plan_challenge(session, prefer_node=prefer_node)
        if challenge is not None:
            return task_view(challenge, session)
    except Exception:
        pass
    return None
