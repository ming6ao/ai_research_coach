"""Admin management helpers: per-candidate summaries and full wipes.

Candidate-scoped rows live in several places:

- ``active_sessions`` (raw sqlite, ``candidate`` column)
- ``task_attempts`` (ORM, ``candidate`` column)
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
        from coach.tasks import SkillBeliefModel, TaskAttemptModel, TaskModel

        attempts = (
            session.scalar(
                select(func.count(TaskAttemptModel.id)).where(
                    TaskAttemptModel.candidate == candidate
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

    total = sessions + attempts + beliefs + owned_tasks
    return {
        "candidate": candidate,
        "active_sessions": sessions,
        "task_attempts": attempts,
        "skill_beliefs": beliefs,
        "owned_tasks": owned_tasks,
        "total": total,
    }


def clear_candidate_everything(candidate: str) -> dict:
    """Delete all candidate-scoped rows; return per-table deleted counts."""
    create_schema()
    deleted: dict[str, int] = {
        "active_sessions": 0,
        "task_attempts": 0,
        "skill_beliefs": 0,
        "owned_tasks": 0,
    }

    with sqlite_conn() as conn:
        cur = conn.execute(
            "DELETE FROM active_sessions WHERE candidate = ?", (candidate,)
        )
        deleted["active_sessions"] = cur.rowcount or 0

    session = learner_session()
    try:
        from coach.tasks import SkillBeliefModel, TaskAttemptModel, TaskModel

        deleted["task_attempts"] = (
            session.query(TaskAttemptModel)
            .filter(TaskAttemptModel.candidate == candidate)
            .delete(synchronize_session=False)
        )
        deleted["skill_beliefs"] = (
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


def stats_summary() -> dict:
    """Counts for the admin stats bar: tasks, attempts, beliefs, sessions."""
    create_schema()
    with sqlite_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM active_sessions").fetchone()
        sessions = row[0] if row else 0
    session = learner_session()
    try:
        from coach.tasks import SkillBeliefModel, TaskAttemptModel, TaskModel

        tasks_total = session.scalar(select(func.count(TaskModel.id))) or 0
        attempts = session.scalar(select(func.count(TaskAttemptModel.id))) or 0
        beliefs = session.scalar(select(func.count(SkillBeliefModel.id))) or 0
    finally:
        session.close()
    return {
        "tasks_total": tasks_total,
        "task_attempts": attempts,
        "skill_beliefs": beliefs,
        "active_sessions": sessions,
    }


def list_candidates(limit: int = 500) -> list[dict]:
    """Distinct candidates seen in sessions/attempts/tasks (for admin UI)."""
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
        from coach.tasks import SkillBeliefModel, TaskAttemptModel, TaskModel

        for model, col in (
            (TaskAttemptModel, TaskAttemptModel.candidate),
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
