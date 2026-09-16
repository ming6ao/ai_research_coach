"""DB-backed task bank: user-created questions + seeded tasks + attempt log.

Tasks live in the shared SQLite file (``data/coach.db``) via the SQLAlchemy
``Base`` in ``coach.db``.

Each task optionally carries ``context_notes``: 2-4 plain-English sentences
(e.g. "A is a prerequisite of B, which is often confused with C") generated
once at creation time. There is no knowledge graph, no nodes/edges, and no
skill tags — every task is eligible for every candidate.

Visibility: a candidate sees system seed rows (``owner='system'``,
``is_public=1``), their own rows, and any public rows. Guests create
public rows (per product decision); signed-in users create private rows
by default with an opt-in ``is_public`` flag.

The overall ability belief (Gaussian mean/variance per candidate) is persisted
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
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False, default=SYSTEM_OWNER)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    scaffold: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    hints_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    context_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default='{"primary": "python", "secondary": []}')
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, default="implement")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    parent_task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cluster_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    followups_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_public: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SkillBeliefModel(Base):
    """Persistent Gaussian belief over a candidate's ability at one level.

    ``level`` is ``'global' | 'family' | 'tag'``; ``key`` is ``'overall'``,
    a family name, or a fine tag name. One row per ``(candidate, level,
    key)``, enforced by a unique index (SQLite cannot add a UNIQUE
    constraint via ``ALTER TABLE``).
    """

    __tablename__ = "user_skill_beliefs"
    __table_args__ = (
        Index("ix_skill_beliefs_candidate", "candidate"),
        Index("uq_user_skill_beliefs", "candidate", "level", "key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    key: Mapped[str] = mapped_column(String(64), nullable=False, default="overall")
    mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    variance: Mapped[float] = mapped_column(Float, nullable=False, default=0.1225)
    questions_answered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def parse_tags(tags_json: Optional[str]) -> dict:
    """Parse a stored ``tags_json`` value into ``{primary, secondary}``.

    Tolerates empty strings and any JSON value; the object default
    ``{"primary": "python", "secondary": []}`` is returned on malformed data
    so a JSON-array default can never crash a scalar ``.get()``.
    """
    try:
        parsed = json.loads(tags_json or "{}")
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    primary = str(parsed.get("primary") or "python").strip() or "python"
    secondary = parsed.get("secondary") or []
    if not isinstance(secondary, list):
        secondary = []
    return {"primary": primary, "secondary": [str(t) for t in secondary]}


def serialize_tags(tags: dict | None) -> str:
    """Serialize a validated tags dict for storage."""
    return json.dumps(tags if isinstance(tags, dict) else {"primary": "python", "secondary": []})


def parse_followups(followups_json: Optional[str]) -> list[dict]:
    """Parse a stored ``followups_json`` value into a list of link dicts.

    Each entry is ``{"task_id": str, "kind": "prereq"|"sibling"}``. Malformed
    input collapses to ``[]`` so a follow-up lookup can never crash.
    """
    try:
        parsed = json.loads(followups_json or "[]")
    except Exception:
        parsed = []
    if not isinstance(parsed, list):
        return []
    out: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or "").strip()
        if not task_id:
            continue
        out.append({
            "task_id": task_id,
            "kind": "sibling" if str(item.get("kind") or "") not in ("prereq", "sibling") else str(item.get("kind")),
        })
    return out


def task_to_dict(model: TaskModel) -> dict:
    try:
        hints = json.loads(model.hints_json or "[]")
    except Exception:
        hints = []
    d: dict[str, Any] = {
        "id": model.id,
        "prompt": model.prompt,
        "difficulty": model.difficulty,
        "max_score": model.max_score,
        "hints": hints,
        "context_notes": getattr(model, "context_notes", "") or "",
        "tags": parse_tags(getattr(model, "tags_json", "")),
        "task_type": getattr(model, "task_type", "") or "implement",
        "source": model.source,
        "is_public": bool(model.is_public),
        "owner": model.owner,
    }
    if model.cluster_id:
        d["cluster_id"] = model.cluster_id
    followups = parse_followups(getattr(model, "followups_json", "") or "[]")
    if followups:
        d["followups"] = followups
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
    tags: Optional[dict] = None,
    task_type: str = "implement",
    cluster_id: Optional[str] = None,
    followups: Optional[list] = None,
) -> dict:
    """Persist a task row and return its dict form.

    ``tags`` is validated against the closed vocabulary
    (``coach.taxonomy.validate``); invalid tags raise ``ValueError``.
    ``cluster_id`` groups related questions into a thread; ``followups`` is a
    list of ``{"task_id", "kind"}`` pointers to related tasks served as
    curated follow-ups after this task is answered.
    """
    from coach.db import create_schema

    create_schema()
    from coach.taxonomy import TASK_TYPES, validate as validate_tags

    if task_type not in TASK_TYPES:
        raise ValueError(f"Unknown task_type: {task_type!r}.")
    tags = validate_tags(tags)
    tid = task_id or f"task_{uuid.uuid4().hex[:10]}"
    session = learner_session()
    try:
        model = TaskModel(
            id=tid,
            owner=owner,
            prompt=prompt,
            scaffold=scaffold,
            difficulty=max(1, min(5, int(difficulty or 2))),
            max_score=max_score or 5,
            hints_json=json.dumps(hints or []),
            context_notes=(context_notes or "").strip()[:2000],
            tags_json=serialize_tags(tags),
            task_type=task_type,
            source=source,
            parent_task_id=parent_task_id,
            target_text=target_text,
            cluster_id=cluster_id,
            followups_json=json.dumps(followups or []),
            is_public=1 if is_public else 0,
            created_at=_utcnow_naive(),
        )
        session.add(model)
        session.commit()
        return task_to_dict(model)
    finally:
        session.close()


def update_task(task_id: str, **fields) -> Optional[dict]:
    """Update whitelisted task columns (v1 PATCH path).

    Allowed: prompt, scaffold, difficulty (1-5), max_score (>=1),
    hints (list), is_public (bool), context_notes (<=2000 chars),
    tags (validated against the vocabulary), task_type, cluster_id,
    followups (list of {"task_id", "kind"} pointers).
    Returns the updated dict, or None when the task does not exist.
    """
    from coach.db import create_schema

    allowed = {
        "prompt", "scaffold", "difficulty", "max_score", "hints",
        "is_public", "context_notes", "tags", "task_type",
        "cluster_id", "followups",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "prompt" in updates and not str(updates["prompt"]).strip():
        raise ValueError("Prompt must not be empty.")
    create_schema()
    from coach.taxonomy import TASK_TYPES, validate as validate_tags

    if "tags" in updates:
        updates["tags"] = validate_tags(updates["tags"])
    if "task_type" in updates and updates["task_type"] not in TASK_TYPES:
        raise ValueError(f"Unknown task_type: {updates['task_type']!r}.")
    session = learner_session()
    try:
        model = session.get(TaskModel, task_id)
        if model is None:
            return None
        if "prompt" in updates:
            model.prompt = str(updates["prompt"]).strip()
        if "scaffold" in updates:
            model.scaffold = updates["scaffold"]
        if "difficulty" in updates:
            model.difficulty = max(1, min(5, int(updates["difficulty"])))
        if "max_score" in updates:
            model.max_score = max(1, int(updates["max_score"]))
        if "hints" in updates:
            model.hints_json = json.dumps(updates["hints"] or [])
        if "is_public" in updates:
            model.is_public = 1 if updates["is_public"] else 0
        if "context_notes" in updates:
            model.context_notes = str(updates["context_notes"] or "").strip()[:2000]
        if "tags" in updates:
            model.tags_json = serialize_tags(updates["tags"])
        if "task_type" in updates:
            model.task_type = updates["task_type"]
        if "cluster_id" in updates:
            model.cluster_id = str(updates["cluster_id"] or "").strip() or None
        if "followups" in updates:
            model.followups_json = json.dumps(parse_followups(json.dumps(updates["followups"] or [])))
        session.commit()
        return task_to_dict(model)
    finally:
        session.close()


def update_task_context(task_id: str, context_notes: str) -> Optional[dict]:
    """Overwrite a task's plain-English context notes (admin edit path)."""
    return update_task(task_id, context_notes=context_notes)


def get_task(task_id: str) -> Optional[dict]:
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        model = session.get(TaskModel, task_id)
        return task_to_dict(model) if model else None
    finally:
        session.close()


def list_visible_tasks(candidate: str) -> list[dict]:
    """Tasks visible to a candidate: system-public + own + public."""
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        stmt = select(TaskModel).order_by(TaskModel.created_at)
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


def record_attempt(
    candidate: str,
    task_id: str,
    fraction: float,
    score: float,
    max_score: float,
    hints_used: Optional[list] = None,
) -> str:
    """Record a scored attempt as a ``session_steps`` row (compat shim).

    ``session_id`` is optional (legacy callers); a synthetic episode id is
    used so rows stay unique under ``uq_session_steps``. Coverage/admin
    aggregate by candidate so a step without a real episode is still counted.
    """
    from coach.steps import insert_step

    return insert_step(
        session_id=f"legacy-{uuid.uuid4().hex[:8]}",
        candidate=candidate,
        step_index=0,
        task={"id": task_id, "max_score": max_score or 5},
        role="bank",
        user_answer="",
        score=score or 0.0,
        max_score=max_score or 5.0,
        fraction=fraction or 0.0,
        reward=fraction or 0.0,
        hints_used=hints_used,
        state_before=None,
        state_after=None,
        result={"score": score or 0.0, "max_score": max_score or 5.0},
        coaching=None,
    )


def _belief_row(session, candidate: str, level: str, key: str):
    return session.scalar(
        select(SkillBeliefModel).where(
            SkillBeliefModel.candidate == candidate,
            SkillBeliefModel.level == level,
            SkillBeliefModel.key == key,
        )
    )


def _belief_to_dict(m: SkillBeliefModel) -> dict:
    return {
        "level": m.level,
        "key": m.key,
        "mean": m.mean,
        "variance": m.variance,
        "questions_answered": m.questions_answered,
    }


def get_skill_belief(candidate: str) -> Optional[dict]:
    """Return the candidate's overall ability belief, if stored.

    Filters on ``level='global'`` / ``key='overall'`` so multiple per-area
    rows never trip a scalar ``MultipleResultsFound``.
    """
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        m = _belief_row(session, candidate, "global", "overall")
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
    candidate: str, mean: float, variance: float, questions_answered: int
) -> None:
    """Persist the candidate's overall ability belief."""
    save_area_belief(candidate, "global", "overall", mean, variance, questions_answered)


def save_area_belief(
    candidate: str,
    level: str,
    key: str,
    mean: float,
    variance: float,
    questions_answered: int,
) -> None:
    """Persist one belief row at ``(candidate, level, key)`` (upsert)."""
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        m = _belief_row(session, candidate, level, key)
        now = _utcnow_naive()
        if m is None:
            session.add(
                SkillBeliefModel(
                    id=str(uuid.uuid4()),
                    candidate=candidate,
                    level=level,
                    key=key,
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


def get_area_beliefs(candidate: str) -> dict[tuple[str, str], dict]:
    """All belief rows for a candidate, keyed by ``(level, key)``."""
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        rows = session.scalars(
            select(SkillBeliefModel).where(SkillBeliefModel.candidate == candidate)
        ).all()
        return {(m.level, m.key): _belief_to_dict(m) for m in rows}
    finally:
        session.close()


# Backwards-compatible aliases for the single overall ability belief.
get_ability = get_skill_belief


def save_ability(candidate: str, mean: float, variance: float, questions_answered: int) -> None:
    return save_skill_belief(candidate, mean, variance, questions_answered)


def list_tasks_for_admin(
    owner: Optional[str] = None,
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
        if q:
            stmt = stmt.where(TaskModel.prompt.contains(q))
        stmt = stmt.limit(limit)
        rows = session.scalars(stmt).all()
        if not rows:
            return []
        from coach.steps import SessionStepModel

        counts = dict(
            session.execute(
                select(
                    SessionStepModel.task_id,
                    func.count(SessionStepModel.id),
                )
                .where(SessionStepModel.task_id.in_([m.id for m in rows]))
                .group_by(SessionStepModel.task_id)
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
    """Delete one task row plus its steps (cascade).

    Returns ``{"deleted_task": 0|1, "deleted_attempts": n}``.
    """
    from coach.steps import delete_steps_for_task

    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        steps = delete_steps_for_task(task_id)
        task = session.get(TaskModel, task_id)
        if task is None:
            session.rollback()
            return {"deleted_task": 0, "deleted_attempts": 0}
        session.delete(task)
        session.commit()
        return {"deleted_task": 1, "deleted_attempts": steps}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
