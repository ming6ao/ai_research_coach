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


def _curated_followup(session, task: Optional[dict] = None) -> Optional[dict]:
    """Return the next unasked curated follow-up of a seed task, or None.

    Follow-up links are pre-authored pointers (``task.followups``) to related
    seeds. The first target not yet asked in this session wins; once all are
    exhausted the selection falls through to the LLM remediation loop.
    """
    if not task:
        return None
    followups = task.get("followups") or []
    if not followups:
        return None
    by_id = {t.get("id"): t for t in (getattr(session, "tasks", []) or [])}
    for link in followups:
        target = by_id.get(link.get("task_id"))
        if target is None or target["id"] in session.asked_task_ids:
            continue
        return target
    return None


def pick_next_task(
    candidate: str,
    session,
    last_submission: Optional[dict] = None,
    sample_top_n: Optional[int] = None,
    family: Optional[str] = None,
) -> dict | None:
    """Choose the next task to present.

    ``last_submission`` carries ``{"task", "result", "coach"}`` from a
    just-recorded submission. ``sample_top_n`` (> 1) samples uniformly from
    the top-N EIG bank candidates instead of always taking the single best;
    it applies to the bank-picker branch only. ``family`` restricts the
    bank-picker branch to tasks in one family (used to seed a session with
    a question in an area); it never affects pending/follow-up branches.
    """
    from coach.picker import next_task as next_task_bank

    # 1. Pending generated follow-up first.
    pending = next(
        (t for t in session.tasks if t.get("generated") and t["id"] not in session.asked_task_ids),
        None,
    )
    if pending is not None:
        return task_view(pending, session)

    # 2. Judge-driven follow-up after a submission. Pre-authored curated
    # follow-up links (``task.followups``) win first; the LLM drill/escalate/
    # pivot loop is the fallback when none apply.
    if last_submission is not None:
        curated = _curated_followup(session, last_submission.get("task"))
        if curated is not None:
            return task_view(curated, session)

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
    nxt = next_task_bank(session, sample_top_n=sample_top_n, family=family)
    if nxt is not None:
        return task_view(nxt, session)

    # 4. Bank exhausted -> mint a fresh adaptive challenge so the session
    # keeps going indefinitely (user exits explicitly via Finish). Steer it
    # toward the least-covered family/tag so scope keeps widening (§5).
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
