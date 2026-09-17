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



