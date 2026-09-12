"""Next-task selection (graph-free hybrid).

1. Pending generated task — an injected follow-up not yet asked surfaces first
   (generated tasks are excluded from the bank picker).
2. Judge-driven follow-up — after a submission, ``plan_followup`` may inject
   one simpler drill task from the judge's gap text.
3. EIG bank picker — ``coach.picker.next_task(session)``.
4. Done — ``None`` when the bank is exhausted and no follow-up remains.
"""

from __future__ import annotations

from typing import Optional

from coach.session import task_view


def pick_next_task(
    candidate: str,
    session,
    last_submission: Optional[dict] = None,
) -> dict | None:
    """Choose the next task to present.

    ``last_submission`` carries ``{"task", "result", "coach"}`` from a
    just-recorded submission.
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
    nxt = next_task_bank(session)
    return task_view(nxt, session) if nxt else None
