"""DB-backed task bank: user-created questions + seeded tasks + attempt log.

Tasks live in the shared SQLite file (``data/coach.db``) via the SQLAlchemy
``Base`` in ``coach.db``.

Each task optionally carries ``context_notes``: 2-4 plain-English sentences
(e.g. "A is a prerequisite of B, which is often confused with C") generated
once at creation time. There is no knowledge graph, no nodes/edges.

Visibility: a candidate sees system seed rows (``owner='system'``,
``is_public=1``), their own rows, and any public rows. Guests create
public rows (per product decision); signed-in users create private rows
by default with an opt-in ``is_public`` flag.

Skill beliefs (Gaussian mean/variance per candidate+skill) are persisted
in ``user_skill_beliefs`` so mastery survives across sessions; the
in-session ``SkillState`` remains the live copy.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Float,
    Index,
    Integer,
    String,
    Text,
    DateTime,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from coach.db import Base, learner_session

SYSTEM_OWNER = "system"


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TaskModel(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_owner", "owner"),
        Index("ix_tasks_skill", "skill"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False, default=SYSTEM_OWNER)
    skill: Mapped[str] = mapped_column(String(128), nullable=False, default="general")
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    scaffold: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    hints_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    context_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    parent_task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_public: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TaskAttemptModel(Base):
    __tablename__ = "task_attempts"
    __table_args__ = (
        Index("ix_task_attempts_candidate", "candidate"),
        Index("ix_task_attempts_task", "task_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate: Mapped[str] = mapped_column(String(255), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fraction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    hints_used_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SkillBeliefModel(Base):
    """Persistent Gaussian belief per (candidate, skill)."""

    __tablename__ = "user_skill_beliefs"
    __table_args__ = (
        Index("ix_skill_beliefs_candidate", "candidate"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate: Mapped[str] = mapped_column(String(255), nullable=False)
    skill: Mapped[str] = mapped_column(String(128), nullable=False)
    mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    variance: Mapped[float] = mapped_column(Float, nullable=False, default=0.1225)
    questions_answered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def task_to_dict(model: TaskModel) -> dict:
    try:
        hints = json.loads(model.hints_json or "[]")
    except Exception:
        hints = []
    d: dict[str, Any] = {
        "id": model.id,
        "skill": model.skill,
        "prompt": model.prompt,
        "difficulty": model.difficulty,
        "max_score": model.max_score,
        "hints": hints,
        "context_notes": getattr(model, "context_notes", "") or "",
        "source": model.source,
        "is_public": bool(model.is_public),
        "owner": model.owner,
    }
    if model.scaffold:
        d["scaffold"] = model.scaffold
    if model.parent_task_id:
        d["parent_task_id"] = model.parent_task_id
    if model.target_text:
        d["target_text"] = model.target_text
        d["generated"] = True
    elif model.source == "generated":
        d["generated"] = True
    return d


def create_task(
    prompt: str,
    skill: str = "general",
    owner: str = SYSTEM_OWNER,
    scaffold: Optional[str] = None,
    difficulty: int = 2,
    max_score: int = 5,
    hints: Optional[list] = None,
    source: str = "user",
    parent_task_id: Optional[str] = None,
    target_text: Optional[str] = None,
    is_public: bool = False,
    task_id: Optional[str] = None,
    context_notes: Optional[str] = None,
) -> dict:
    """Persist a task row and return its dict form."""
    from coach.db import create_schema

    create_schema()
    tid = task_id or f"task_{uuid.uuid4().hex[:10]}"
    session = learner_session()
    try:
        model = TaskModel(
            id=tid,
            owner=owner,
            skill=skill or "general",
            prompt=prompt,
            scaffold=scaffold,
            difficulty=max(1, min(5, int(difficulty or 2))),
            max_score=max_score or 5,
            hints_json=json.dumps(hints or []),
            context_notes=(context_notes or "").strip()[:2000],
            source=source,
            parent_task_id=parent_task_id,
            target_text=target_text,
            is_public=1 if is_public else 0,
            created_at=_utcnow_naive(),
        )
        session.add(model)
        session.commit()
        return task_to_dict(model)
    finally:
        session.close()


def update_task_context(task_id: str, context_notes: str) -> Optional[dict]:
    """Overwrite a task's plain-English context notes (admin edit path)."""
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        model = session.get(TaskModel, task_id)
        if model is None:
            return None
        model.context_notes = (context_notes or "").strip()[:2000]
        session.commit()
        return task_to_dict(model)
    finally:
        session.close()


def get_task(task_id: str) -> Optional[dict]:
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        model = session.get(TaskModel, task_id)
        return task_to_dict(model) if model else None
    finally:
        session.close()


def list_visible_tasks(candidate: str, skill: Optional[str] = None) -> list[dict]:
    """Tasks visible to a candidate: system-public + own + public."""
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        stmt = select(TaskModel).order_by(TaskModel.created_at)
        if skill:
            stmt = stmt.where(TaskModel.skill == skill)
        rows = session.scalars(stmt).all()
        out = []
        for m in rows:
            if m.owner == SYSTEM_OWNER and m.is_public:
                out.append(task_to_dict(m))
            elif m.owner == candidate:
                out.append(task_to_dict(m))
            elif m.is_public:
                out.append(task_to_dict(m))
        return out
    finally:
        session.close()


def count_tasks() -> int:
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        return session.query(TaskModel).count()
    finally:
        session.close()


def record_attempt(
    candidate: str,
    task_id: str,
    fraction: float,
    score: float,
    max_score: float,
    hints_used: Optional[list] = None,
) -> str:
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        aid = str(uuid.uuid4())
        session.add(
            TaskAttemptModel(
                id=aid,
                candidate=candidate,
                task_id=task_id,
                fraction=max(0.0, min(1.0, fraction)),
                score=score,
                max_score=max_score,
                hints_used_json=json.dumps(hints_used or []),
                created_at=_utcnow_naive(),
            )
        )
        session.commit()
        return aid
    finally:
        session.close()


def get_skill_belief(candidate: str, skill: str) -> Optional[dict]:
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        m = session.scalar(
            select(SkillBeliefModel).where(
                SkillBeliefModel.candidate == candidate,
                SkillBeliefModel.skill == skill,
            )
        )
        if m is None:
            return None
        return {
            "mean": m.mean,
            "variance": m.variance,
            "questions_answered": m.questions_answered,
        }
    finally:
        session.close()


def save_skill_belief(
    candidate: str, skill: str, mean: float, variance: float, questions_answered: int
) -> None:
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        m = session.scalar(
            select(SkillBeliefModel).where(
                SkillBeliefModel.candidate == candidate,
                SkillBeliefModel.skill == skill,
            )
        )
        now = _utcnow_naive()
        if m is None:
            session.add(
                SkillBeliefModel(
                    id=str(uuid.uuid4()),
                    candidate=candidate,
                    skill=skill,
                    mean=mean,
                    variance=variance,
                    questions_answered=questions_answered,
                    updated_at=now,
                )
            )
        else:
            m.mean = mean
            m.variance = variance
            m.questions_answered = questions_answered
            m.updated_at = now
        session.commit()
    finally:
        session.close()


def task_stats(task_id: str) -> dict:
    """Aggregate attempt stats for a task (solve-rate calibration)."""
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        rows = (
            session.scalars(
                select(TaskAttemptModel).where(TaskAttemptModel.task_id == task_id)
            ).all()
        )
        if not rows:
            return {"attempts": 0, "mean_fraction": 0.5}
        return {
            "attempts": len(rows),
            "mean_fraction": sum(r.fraction for r in rows) / len(rows),
        }
    finally:
        session.close()


def task_attempt_count(task_id: str) -> int:
    """Number of attempt rows referencing a task."""
    from coach.db import create_schema
    from sqlalchemy import func

    create_schema()
    session = learner_session()
    try:
        return (
            session.scalar(
                select(func.count(TaskAttemptModel.id)).where(
                    TaskAttemptModel.task_id == task_id
                )
            )
            or 0
        )
    finally:
        session.close()


def list_tasks_for_admin(
    owner: Optional[str] = None,
    skill: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """List tasks for the admin UI, newest last, with per-task attempt counts."""
    from coach.db import create_schema
    from sqlalchemy import func

    create_schema()
    limit = max(1, min(500, int(limit or 200)))
    session = learner_session()
    try:
        stmt = select(TaskModel).order_by(TaskModel.created_at)
        if owner:
            stmt = stmt.where(TaskModel.owner == owner)
        if skill:
            stmt = stmt.where(TaskModel.skill == skill)
        if q:
            stmt = stmt.where(TaskModel.prompt.contains(q))
        stmt = stmt.limit(limit)
        rows = session.scalars(stmt).all()
        if not rows:
            return []
        counts = dict(
            session.execute(
                select(
                    TaskAttemptModel.task_id,
                    func.count(TaskAttemptModel.id),
                )
                .where(TaskAttemptModel.task_id.in_([m.id for m in rows]))
                .group_by(TaskAttemptModel.task_id)
            ).all()
        )
        out = []
        for m in rows:
            d = task_to_dict(m)
            d["attempt_count"] = counts.get(m.id, 0)
            d["created_at"] = (
                m.created_at.isoformat() if m.created_at else None
            )
            out.append(d)
        return out
    finally:
        session.close()


def delete_task(task_id: str) -> dict:
    """Delete one task row plus its attempts (cascade).

    Returns ``{"deleted_task": 0|1, "deleted_attempts": n}``.
    """
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        attempts = (
            session.query(TaskAttemptModel)
            .filter(TaskAttemptModel.task_id == task_id)
            .delete(synchronize_session=False)
        )
        task = session.get(TaskModel, task_id)
        if task is None:
            session.rollback()
            return {"deleted_task": 0, "deleted_attempts": 0}
        session.delete(task)
        session.commit()
        return {"deleted_task": 1, "deleted_attempts": attempts}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
