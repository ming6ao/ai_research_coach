"""Next-task selection (graph-free hybrid, open-ended).

1. Pending generated task — an injected follow-up not yet asked surfaces first
   (generated tasks are excluded from the bank picker).
2. Active phased task — a ``delivery='phased'`` task that has been started but
   not completed continues (next phase after a pass, or the same phase after a
   failed attempt). Its view carries the candidate's prior code forward as
   ``previous_code``.
3. Judge-driven follow-up — after a submission, ``plan_followup`` may inject
   an adaptive drill (simpler on failure; harder escalation or sibling
   prerequisite pivot after a solved follow-up).
4. EIG bank picker — ``coach.picker.next_task(session)``.
5. Fresh challenge — when the bank is exhausted, mint an ability-matched
   task via ``plan_challenge`` so the session keeps going indefinitely.
   ``None`` is returned only when generation also fails; the session ends
   explicitly when the user chooses Finish / View progress.

Version chains are retired from selection: successors are never picked and
are migrated into phased tasks (see ``coach.tasks.merge_version_chain``).
"""

from __future__ import annotations

from typing import Optional

from coach.session import is_phased, task_view


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
    """True once a phased task has at least one attempt or passed phase."""
    task_id = task.get("id")
    return bool(
        session.task_progress.get(task_id, 0)
        or session.phase_attempts.get(task_id, 0)
    )


def _active_phased_task(session, task: Optional[dict] = None) -> Optional[dict]:
    """A started-but-unfinished phased task, or None.

    Called with the just-submitted task (post-submit path) or without one
    (resume path, where it scans the session's tasks).
    """
    def unfinished(t: dict) -> bool:
        return (
            is_phased(t)
            and t.get("id") not in session.asked_task_ids
            and session.task_progress.get(t.get("id"), 0) < len(t.get("parts") or [])
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
    family: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict | None:
    """Choose the next task to present.

    ``last_submission`` carries ``{"task", "answer", "result", "coach"}``
    from a just-recorded submission (``answer`` is the candidate's code,
    carried into the next phase). ``sample_top_n`` (> 1) samples uniformly
    from the top-N EIG bank candidates instead of always taking the single
    best; it applies to the bank-picker branch only. ``family`` restricts the
    bank-picker branch to tasks in one family (used to seed a session with a
    question in an area); it never affects pending/follow-up branches.
    ``session_id`` lets the resume path fetch the candidate's prior code for
    an in-progress phased task.
    """
    from coach.picker import next_task as next_task_bank

    # 1. Pending generated follow-up first.
    pending = next(
        (t for t in session.tasks if t.get("generated") and t["id"] not in session.asked_task_ids),
        None,
    )
    if pending is not None:
        return task_view(pending, session)

    # 2. Continue / retry an active phased task.
    active = _active_phased_task(session, (last_submission or {}).get("task"))
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
    nxt = next_task_bank(session, sample_top_n=sample_top_n, family=family)
    if nxt is not None:
        return task_view(nxt, session)

    # 5. Bank exhausted -> mint a fresh adaptive challenge so the session
    # keeps going indefinitely (user exits explicitly via Finish). Steer it
    # toward the least-covered family/tag so scope keeps widening.
    try:
        from coach.remediation import least_covered, plan_challenge

        prefer_family, prefer_tag = least_covered(session)
        challenge = plan_challenge(
            session, prefer_family=prefer_family, prefer_tag=prefer_tag
        )
        if challenge is not None:
            return task_view(challenge, session)
    except Exception:
        pass
    return None
