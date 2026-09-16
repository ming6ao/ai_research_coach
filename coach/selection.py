"""Next-task selection (graph-free hybrid, open-ended).

1. Pending generated task — an injected follow-up not yet asked surfaces first
   (generated tasks are excluded from the bank picker).
2. Version successor — after a submission (or on resume), the unasked task
   whose ``depends_on_task_id`` equals the last answered task's id (e.g. a
   thread-safe queue follows a plain bounded queue).
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

from coach.session import task_view


def _version_successor(session, task: Optional[dict] = None) -> Optional[dict]:
    """Return the unasked version successor of ``task``, or None.

    Without an explicit task (resume path) the last answered task is used.
    A successor is a task whose ``depends_on_task_id`` points at ``task`` and
    that has not been asked in this session yet.
    """
    if task is None:
        if session.results:
            last = session.results[-1]
            by_id = {t.get("id"): t for t in (getattr(session, "tasks", []) or [])}
            task = by_id.get(getattr(last, "task_id", None))
    if not task:
        return None
    for t in (getattr(session, "tasks", []) or []):
        if t.get("depends_on_task_id") == task["id"] and t["id"] not in session.asked_task_ids:
            return t
    return None


def _previous_code_for(session_id: Optional[str], successor: dict) -> Optional[str]:
    """Fetch the predecessor's submitted code from ``session_steps``."""
    if not session_id:
        return None
    pred_id = successor.get("depends_on_task_id")
    if not pred_id:
        return None
    try:
        from coach.steps import answer_for_task

        return answer_for_task(session_id, pred_id)
    except Exception:
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
    from a just-recorded submission (``answer`` is the predecessor's code,
    carried forward into a version successor). ``sample_top_n`` (> 1)
    samples uniformly from the top-N EIG bank candidates instead of always
    taking the single best; it applies to the bank-picker branch only.
    ``family`` restricts the bank-picker branch to tasks in one family (used
    to seed a session with a question in an area); it never affects
    pending/follow-up branches. ``session_id`` lets the resume path fetch a
    predecessor's code from ``session_steps`` for version successors.
    """
    from coach.picker import next_task as next_task_bank

    # 1. Pending generated follow-up first.
    pending = next(
        (t for t in session.tasks if t.get("generated") and t["id"] not in session.asked_task_ids),
        None,
    )
    if pending is not None:
        return task_view(pending, session)

    # 2. Version successor after a submission (or on resume).
    successor = _version_successor(session, (last_submission or {}).get("task"))
    if successor is not None:
        previous_code = None
        if last_submission and last_submission.get("answer"):
            previous_code = last_submission.get("answer")
        else:
            previous_code = _previous_code_for(session_id, successor)
        return task_view(successor, session, previous_code=previous_code)

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