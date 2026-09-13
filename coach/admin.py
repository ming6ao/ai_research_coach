"""Admin management helpers: per-candidate summaries and full wipes.

Candidate-scoped rows live in several places:

- ``active_sessions`` (raw sqlite, ``candidate`` column)
- ``session_steps`` (ORM, ``candidate`` column)
- ``user_skill_beliefs`` (ORM, ``candidate`` column)
- ``tasks`` (ORM, ``owner`` column)
"""

from __future__ import annotations

from sqlalchemy import func, select

from coach.db import create_schema, learner_session, sqlite_conn


def candidate_summary(candidate: str) -> dict:
    """Count candidate-scoped rows per table (dry-run preview for wipes)."""
    create_schema()
    with sqlite_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM active_sessions WHERE candidate = ?",
            (candidate,),
        ).fetchone()
        sessions = row[0] if row else 0

    session = learner_session()
    try:
        from coach.steps import SessionStepModel
        from coach.tasks import SkillBeliefModel, TaskModel

        steps = (
            session.scalar(
                select(func.count(SessionStepModel.id)).where(
                    SessionStepModel.candidate == candidate
                )
            )
            or 0
        )
        beliefs = (
            session.scalar(
                select(func.count(SkillBeliefModel.id)).where(
                    SkillBeliefModel.candidate == candidate
                )
            )
            or 0
        )
        owned_tasks = (
            session.scalar(
                select(func.count(TaskModel.id)).where(
                    TaskModel.owner == candidate
                )
            )
            or 0
        )
    finally:
        session.close()

    total = sessions + steps + beliefs + owned_tasks
    return {
        "candidate": candidate,
        "active_sessions": sessions,
        "session_steps": steps,
        "ability_beliefs": beliefs,
        "owned_tasks": owned_tasks,
        "total": total,
    }


def clear_candidate_everything(candidate: str) -> dict:
    """Delete all candidate-scoped rows; return per-table deleted counts."""
    create_schema()
    deleted: dict[str, int] = {
        "active_sessions": 0,
        "session_steps": 0,
        "ability_beliefs": 0,
        "owned_tasks": 0,
    }

    with sqlite_conn() as conn:
        cur = conn.execute(
            "DELETE FROM active_sessions WHERE candidate = ?", (candidate,)
        )
        deleted["active_sessions"] = cur.rowcount or 0

    session = learner_session()
    try:
        from coach.steps import SessionStepModel
        from coach.tasks import SkillBeliefModel, TaskModel

        deleted["session_steps"] = (
            session.query(SessionStepModel)
            .filter(SessionStepModel.candidate == candidate)
            .delete(synchronize_session=False)
        )
        deleted["ability_beliefs"] = (
            session.query(SkillBeliefModel)
            .filter(SkillBeliefModel.candidate == candidate)
            .delete(synchronize_session=False)
        )
        deleted["owned_tasks"] = (
            session.query(TaskModel)
            .filter(TaskModel.owner == candidate)
            .delete(synchronize_session=False)
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    deleted["total"] = sum(deleted.values())
    return {"candidate": candidate, "deleted": deleted}


def _is_stale_seed_id(tid: str) -> bool:
    """True for seed-bank rows outside the current catalog.

    The canonical catalog ids are ``seed_<slug>``. Everything else tagged
    ``source='seed'`` is stale: the legacy ``seed_seed_*`` duplicates and the
    pre-catalog ``mr_*``/``mi_*`` tasks.
    """
    return tid.startswith("seed_seed_") or not tid.startswith("seed_")


def stale_seed_cleanup(preview: bool = True) -> dict:
    """Identify/delete stale seed-bank rows and everything referencing them.

    Stale = ``source='seed'`` rows that are not in the current catalog
    (``seed_seed_*`` duplicates and ``mr_*``/``mi_*`` pre-catalog tasks).
    The cascade also removes:

    - child tasks whose ``parent_task_id`` points at a stale row
      (remediation drills),
    - ``active_sessions`` whose ``session_json`` references any stale/child id,
    - ``session_steps`` rows for the deleted tasks or sessions.

    ``preview=True`` returns the ids/counts without mutating anything;
    ``preview=False`` deletes them and returns what was removed.
    """
    from sqlalchemy import or_

    from coach.steps import SessionStepModel
    from coach.tasks import SkillBeliefModel, TaskModel

    create_schema()
    session = learner_session()
    try:
        seed_ids = session.scalars(
            select(TaskModel.id).where(TaskModel.source == "seed")
        ).all()
        stale_ids = sorted(t for t in seed_ids if _is_stale_seed_id(t))

        child_ids: list[str] = []
        if stale_ids:
            child_ids = sorted(
                session.scalars(
                    select(TaskModel.id).where(TaskModel.parent_task_id.in_(stale_ids))
                ).all()
            )
        doomed = set(stale_ids) | set(child_ids)

        with sqlite_conn() as conn:
            session_rows = conn.execute(
                "SELECT session_id, session_json FROM active_sessions"
            ).fetchall()
        session_ids = sorted(
            sid
            for sid, sj in session_rows
            if sj and any(t in sj for t in doomed)
        )

        step_ids: list[str] = []
        if doomed or session_ids:
            step_ids = sorted(
                session.scalars(
                    select(SessionStepModel.id).where(
                        or_(
                            SessionStepModel.task_id.in_(doomed or [""]),
                            SessionStepModel.session_id.in_(session_ids or [""]),
                        )
                    )
                ).all()
            )
    finally:
        session.close()

    result: dict = {
        "preview": preview,
        "stale_tasks": stale_ids,
        "child_tasks": child_ids,
        "sessions": session_ids,
        "session_steps": step_ids,
        "counts": {
            "stale_tasks": len(stale_ids),
            "child_tasks": len(child_ids),
            "sessions": len(session_ids),
            "session_steps": len(step_ids),
        },
    }

    if preview:
        return result

    with sqlite_conn() as conn:
        if session_ids:
            conn.execute(
                "DELETE FROM active_sessions WHERE session_id IN (%s)"
                % ",".join("?" * len(session_ids)),
                session_ids,
            )
        conn.commit()

    session = learner_session()
    try:
        if step_ids:
            session.query(SessionStepModel).filter(
                SessionStepModel.id.in_(step_ids)
            ).delete(synchronize_session=False)
        if child_ids:
            session.query(TaskModel).filter(TaskModel.id.in_(child_ids)).delete(
                synchronize_session=False
            )
        if stale_ids:
            session.query(TaskModel).filter(TaskModel.id.in_(stale_ids)).delete(
                synchronize_session=False
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return result


def guest_data_cleanup(preview: bool = True) -> dict:
    """Identify/delete all guest-scoped rows (candidate/owner LIKE 'guest-%').

    Covers ``active_sessions``, ``session_steps``, ``user_skill_beliefs``, and
    tasks owned by a guest identity. ``preview=True`` returns the ids/counts
    without mutating anything; ``preview=False`` deletes them.
    """
    from coach.steps import SessionStepModel
    from coach.tasks import SkillBeliefModel, TaskModel

    create_schema()
    with sqlite_conn() as conn:
        session_ids = sorted(
            r[0]
            for r in conn.execute(
                "SELECT session_id FROM active_sessions WHERE candidate LIKE 'guest-%'"
            ).fetchall()
        )
    session = learner_session()
    try:
        step_ids = sorted(
            session.scalars(
                select(SessionStepModel.id).where(
                    SessionStepModel.candidate.like("guest-%")
                )
            ).all()
        )
        belief_ids = sorted(
            session.scalars(
                select(SkillBeliefModel.id).where(
                    SkillBeliefModel.candidate.like("guest-%")
                )
            ).all()
        )
        owned_task_ids = sorted(
            session.scalars(
                select(TaskModel.id).where(TaskModel.owner.like("guest-%"))
            ).all()
        )
    finally:
        session.close()

    result: dict = {
        "preview": preview,
        "sessions": session_ids,
        "session_steps": step_ids,
        "ability_beliefs": belief_ids,
        "owned_tasks": owned_task_ids,
        "counts": {
            "sessions": len(session_ids),
            "session_steps": len(step_ids),
            "ability_beliefs": len(belief_ids),
            "owned_tasks": len(owned_task_ids),
        },
    }

    if preview:
        return result

    session = learner_session()
    try:
        if step_ids:
            session.query(SessionStepModel).filter(
                SessionStepModel.id.in_(step_ids)
            ).delete(synchronize_session=False)
        if belief_ids:
            session.query(SkillBeliefModel).filter(
                SkillBeliefModel.id.in_(belief_ids)
            ).delete(synchronize_session=False)
        if owned_task_ids:
            session.query(TaskModel).filter(TaskModel.id.in_(owned_task_ids)).delete(
                synchronize_session=False
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    with sqlite_conn() as conn:
        if session_ids:
            conn.execute(
                "DELETE FROM active_sessions WHERE session_id IN (%s)"
                % ",".join("?" * len(session_ids)),
                session_ids,
            )
        conn.commit()
    return result


def stats_summary() -> dict:
    """Counts for the admin stats bar: tasks, steps, beliefs, sessions."""
    create_schema()
    with sqlite_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM active_sessions").fetchone()
        sessions = row[0] if row else 0
    session = learner_session()
    try:
        from coach.steps import SessionStepModel
        from coach.tasks import SkillBeliefModel, TaskModel

        tasks_total = session.scalar(select(func.count(TaskModel.id))) or 0
        steps = session.scalar(select(func.count(SessionStepModel.id))) or 0
        beliefs = session.scalar(select(func.count(SkillBeliefModel.id))) or 0
    finally:
        session.close()
    return {
        "tasks_total": tasks_total,
        "session_steps": steps,
        "ability_beliefs": beliefs,
        "active_sessions": sessions,
    }


def list_candidates(limit: int = 500) -> list[dict]:
    """Distinct candidates seen in sessions/steps/tasks (for admin UI)."""
    create_schema()
    seen: dict[str, None] = {}
    with sqlite_conn() as conn:
        try:
            rows = conn.execute(
                "SELECT DISTINCT candidate FROM active_sessions ORDER BY candidate LIMIT ?",
                (limit,),
            ).fetchall()
            for (c,) in rows:
                if c:
                    seen[c] = None
        except Exception:
            pass
    session = learner_session()
    try:
        from coach.steps import SessionStepModel
        from coach.tasks import SkillBeliefModel, TaskModel

        for model, col in (
            (SessionStepModel, SessionStepModel.candidate),
            (SkillBeliefModel, SkillBeliefModel.candidate),
            (TaskModel, TaskModel.owner),
        ):
            try:
                for (c,) in session.execute(select(col).distinct().limit(limit)).all():
                    if c:
                        seen[c] = None
            except Exception:
                pass
    finally:
        session.close()
    return [{"candidate": c} for c in sorted(seen)][:limit]
