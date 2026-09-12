"""Next-task selection (graph-free hybrid, open-ended).

1. Pending generated task — an injected follow-up not yet asked surfaces first
   (generated tasks are excluded from the bank picker).
2. Judge-driven follow-up — after a submission, ``plan_followup`` may inject
   an adaptive drill (simpler on failure; harder escalation or sibling
   prerequisite pivot after a solved follow-up).
3. EIG bank picker — ``coach.picker.next_task(session)``.
4. Fresh challenge — when the bank is exhausted, mint an ability-matched
   task via ``plan_challenge`` so the session keeps going indefinitely.
   ``None`` is returned only when generation also fails; the session ends
   explicitly when the user chooses Finish / View progress.
"""

from __future__ import annotations

from typing import Optional

from coach.session import task_view


def pick_next_task(
    candidate: str,
    session,
    last_submission: Optional[dict] = None,
    sample_top_n: Optional[int] = None,
) -> dict | None:
    """Choose the next task to present.

    ``last_submission`` carries ``{"task", "result", "coach"}`` from a
    just-recorded submission. ``sample_top_n`` (> 1) samples uniformly from
    the top-N EIG bank candidates instead of always taking the single best;
    it applies to the bank-picker branch only.
    """
    from coach.picker import next_task as next_task_bank

    # 1. Pending generated follow-up first.
    pending = next(
        (t for t in session.tasks if t.get("generated") and t["id"] not in session.asked_task_ids),
        None,
    )
    if pending is not None:
        return task_view(pending, session)

    # 2. Judge-driven follow-up after a submission.
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

    # 3. EIG bank picker.
    nxt = next_task_bank(session, sample_top_n=sample_top_n)
    if nxt is not None:
        return task_view(nxt, session)

    # 4. Bank exhausted -> mint a fresh adaptive challenge so the session
    # keeps going indefinitely (user exits explicitly via Finish).
    try:
        from coach.remediation import plan_challenge

        challenge = plan_challenge(session)
        if challenge is not None:
            return task_view(challenge, session)
    except Exception:
        pass
    return None
