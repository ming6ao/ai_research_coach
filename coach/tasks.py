"""DB-backed task bank: user/admin-created questions + LLM-generated tasks.

Tasks live in the shared SQLite file (``data/coach.db``) via the SQLAlchemy
``Base`` in ``coach.db`` — the database is the source of truth for tasks
(there is no code-embedded catalog).

Each task optionally carries ``context_notes``: 2-4 plain-English sentences
generated once at creation time. There is no knowledge graph, no nodes/edges,
and no skill tags — every task is eligible for every candidate.

A task may be a **code block**: a task-level ``scaffold`` covering a set of
related functions (``parts_json``). A part is
``{key, prompt, tags, max_score, difficulty}``; parts carry no scaffold and no
hints. Tasks can be linked into **version chains** via ``depends_on_task_id`` /
``version_root_id``: a later version modifies the same code and is evaluated
on its own criteria, with the predecessor's submitted answer carried forward
as context.

Visibility: a candidate sees public system rows (``owner='system'``,
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
from coach.config import DELIVERIES, default_pass_score

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
    parts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    context_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default='{"primary": "python", "secondary": []}')
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, default="implement")
    language: Mapped[str] = mapped_column(String(32), nullable=False, default="python")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    parent_task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    depends_on_task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    version_root_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    delivery: Mapped[str] = mapped_column(String(16), nullable=False, default="block")
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


# Monaco editor language ids accepted for a code task. Unknown values fall
# back to "python" so a task can never break the editor.
ALLOWED_LANGUAGES = {
    "python",
    "cpp",
    "c",
    "javascript",
    "typescript",
    "java",
    "go",
    "rust",
}


def normalize_language(language: Optional[str]) -> str:
    """Canonical editor language id; unknown/empty -> ``python``."""
    key = str(language or "").strip().lower()
    if key in {"c++", "cxx", "cc", "hpp"}:
        key = "cpp"
    return key if key in ALLOWED_LANGUAGES else "python"


def parse_parts(parts_json: Optional[str]) -> list[dict]:
    """Parse a stored ``parts_json`` value into a list of part dicts.

    A part is ``{key, prompt, tags, max_score, difficulty}``. Malformed input
    collapses to ``[]``; numeric fields are clamped and unknown tags fall
    back to the default tags so a reader can never crash on bad data
    (strict validation happens at write time).
    """
    try:
        parsed = json.loads(parts_json or "[]")
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not key or not prompt or key in seen:
            continue
        seen.add(key)
        part_max = max(1, min(100, int(item.get("max_score") or 5)))
        part_difficulty = max(1, min(5, int(item.get("difficulty") or 1)))
        try:
            pass_score = int(item.get("pass_score"))
        except (TypeError, ValueError):
            pass_score = default_pass_score(part_max)
        entry = {
            "key": key,
            "prompt": prompt,
            "tags": parse_tags(json.dumps(item.get("tags")) if not isinstance(item.get("tags"), str) else item.get("tags")),
            "max_score": part_max,
            "difficulty": part_difficulty,
            "pass_score": max(0, min(part_max, pass_score)),
        }
        scaffold = str(item.get("scaffold") or "").strip()[:16000]
        if scaffold:
            entry["scaffold"] = scaffold
        out.append(entry)
    return out


def serialize_parts(parts: Optional[list]) -> str:
    """Serialize a validated parts list for storage."""
    return json.dumps(parts or [])


def validate_parts(parts) -> list[dict]:
    """Validate a parts list; returns the normalized list. Raises ValueError.

    Every part needs a unique ``key``, a non-empty ``prompt``,
    taxonomy-validated ``tags``, a ``max_score`` in 1..100 and a
    ``difficulty`` in 1..5.
    """
    from coach.taxonomy import validate as validate_tags

    if parts is None:
        return []
    if not isinstance(parts, list):
        raise ValueError("parts must be a list.")
    out: list[dict] = []
    seen: set[str] = set()
    for item in parts:
        if not isinstance(item, dict):
            raise ValueError("Each part must be an object.")
        key = str(item.get("key") or "").strip()
        if not key:
            raise ValueError("Each part needs a key.")
        if key in seen:
            raise ValueError(f"Duplicate part key: {key!r}.")
        prompt = str(item.get("prompt") or "").strip()
        if not prompt:
            raise ValueError(f"Part {key!r} needs a prompt.")
        seen.add(key)
        try:
            tags = validate_tags(item.get("tags"))
        except ValueError as e:
            raise ValueError(f"Part {key!r}: {e}")
        try:
            max_score = max(1, min(100, int(item.get("max_score") or 5)))
        except (TypeError, ValueError):
            raise ValueError(f"Part {key!r} max_score must be an integer 1..100.")
        try:
            difficulty = max(1, min(5, int(item.get("difficulty") or 1)))
        except (TypeError, ValueError):
            raise ValueError(f"Part {key!r} difficulty must be an integer 1..5.")
        scaffold = str(item.get("scaffold") or "").strip()
        if len(scaffold) > 16000:
            raise ValueError(f"Part {key!r} scaffold must be at most 16000 characters.")
        try:
            pass_score = int(item.get("pass_score"))
        except (TypeError, ValueError):
            pass_score = default_pass_score(max_score)
        pass_score = max(0, min(max_score, pass_score))
        part = {
            "key": key,
            "prompt": prompt,
            "tags": tags,
            "max_score": max_score,
            "difficulty": difficulty,
            "pass_score": pass_score,
        }
        if scaffold:
            part["scaffold"] = scaffold
        out.append(part)
    return out


def derive_block_tags(parts: list[dict]) -> dict:
    """Block-level tags from its parts: first part's primary + up to 2 others.

    The belief system consumes each part's own tags; the block-level tags are
    a display/picker summary derived here when the author omits them.
    """
    primaries = [p["tags"]["primary"] for p in parts]
    if not primaries:
        return {"primary": "python", "secondary": []}
    primary = primaries[0]
    secondary: list[str] = []
    for tag in primaries[1:]:
        if tag != primary and tag not in secondary:
            secondary.append(tag)
    return {"primary": primary, "secondary": secondary[:2]}


def task_to_dict(model: TaskModel) -> dict:
    d: dict[str, Any] = {
        "id": model.id,
        "prompt": model.prompt,
        "difficulty": model.difficulty,
        "max_score": model.max_score,
        "context_notes": getattr(model, "context_notes", "") or "",
        "tags": parse_tags(getattr(model, "tags_json", "")),
        "task_type": getattr(model, "task_type", "") or "implement",
        "language": normalize_language(getattr(model, "language", "")),
        "source": model.source,
        "is_public": bool(model.is_public),
        "owner": model.owner,
        "delivery": (getattr(model, "delivery", "") or "block"),
    }
    parts = parse_parts(getattr(model, "parts_json", "") or "[]")
    if parts:
        d["parts"] = parts
    version_index = int(getattr(model, "version_index", 1) or 1)
    if version_index > 1:
        d["version_index"] = version_index
    if getattr(model, "depends_on_task_id", None):
        d["depends_on_task_id"] = model.depends_on_task_id
    version_root_id = getattr(model, "version_root_id", None)
    if version_root_id and version_root_id != model.id:
        d["version_root_id"] = version_root_id
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
    difficulty: Optional[int] = None,
    max_score: Optional[int] = None,
    source: str = "user",
    parent_task_id: Optional[str] = None,
    target_text: Optional[str] = None,
    is_public: bool = False,
    task_id: Optional[str] = None,
    context_notes: Optional[str] = None,
    tags: Optional[dict] = None,
    task_type: str = "implement",
    language: Optional[str] = None,
    parts: Optional[list] = None,
    version_index: Optional[int] = None,
    depends_on_task_id: Optional[str] = None,
    version_root_id: Optional[str] = None,
    delivery: str = "block",
) -> dict:
    """Persist a task row and return its dict form.

    ``tags`` and each part's ``tags`` are validated against the closed
    vocabulary (``coach.taxonomy.validate``); invalid tags raise
    ``ValueError``. A code block may carry ``parts``; when ``tags`` is
    omitted for a block they are auto-derived from the parts. ``max_score``
    and ``difficulty`` default to the parts' aggregates when omitted.

    Version chains: when ``depends_on_task_id`` is set the row is a successor
    — the chain root is resolved from the predecessor (unless
    ``version_root_id`` is given) and ``version_index`` defaults to the
    predecessor's index + 1.
    """
    from coach.db import create_schema

    create_schema()
    from coach.taxonomy import TASK_TYPES, validate as validate_tags

    if task_type not in TASK_TYPES:
        raise ValueError(f"Unknown task_type: {task_type!r}.")
    delivery = str(delivery or "block").strip().lower() or "block"
    if delivery not in DELIVERIES:
        raise ValueError(f"Unknown delivery: {delivery!r}. Expected one of: {', '.join(DELIVERIES)}.")
    parts = validate_parts(parts)
    tid = task_id or f"task_{uuid.uuid4().hex[:10]}"

    resolved_root = version_root_id
    resolved_index = version_index
    if depends_on_task_id:
        prev = get_task(depends_on_task_id)
        if prev is None:
            raise ValueError(f"depends_on_task_id {depends_on_task_id!r} not found.")
        resolved_root = resolved_root or prev.get("version_root_id") or prev.get("id")
        resolved_index = resolved_index or (prev.get("version_index") or 1) + 1
    else:
        resolved_index = resolved_index or 1
        resolved_root = resolved_root or tid

    if tags is None:
        tags = derive_block_tags(parts) if parts else {"primary": "python", "secondary": []}
    tags = validate_tags(tags)

    if parts:
        if difficulty is None:
            difficulty = max(p["difficulty"] for p in parts)
        if max_score is None:
            max_score = sum(p["max_score"] for p in parts)
    difficulty = max(1, min(5, int(difficulty or 2)))
    max_score = max(1, int(max_score or 5))

    session = learner_session()
    try:
        model = TaskModel(
            id=tid,
            owner=owner,
            prompt=prompt,
            scaffold=scaffold,
            difficulty=difficulty,
            max_score=max_score,
            parts_json=serialize_parts(parts),
            context_notes=(context_notes or "").strip()[:2000],
            tags_json=serialize_tags(tags),
            task_type=task_type,
            language=normalize_language(language),
            source=source,
            parent_task_id=parent_task_id,
            target_text=target_text,
            version_index=max(1, int(resolved_index or 1)),
            depends_on_task_id=depends_on_task_id,
            version_root_id=resolved_root,
            delivery=delivery,
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
    parts (validated list), is_public (bool), context_notes (<=2000 chars),
    tags (validated against the vocabulary), task_type, version_index,
    depends_on_task_id, version_root_id.
    Returns the updated dict, or None when the task does not exist.
    """
    from coach.db import create_schema

    allowed = {
        "prompt", "scaffold", "difficulty", "max_score", "parts",
        "is_public", "context_notes", "tags", "task_type", "language",
        "version_index", "depends_on_task_id", "version_root_id",
        "owner", "delivery",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "prompt" in updates and not str(updates["prompt"]).strip():
        raise ValueError("Prompt must not be empty.")
    if "owner" in updates and not str(updates["owner"]).strip():
        raise ValueError("Owner must not be empty.")
    create_schema()
    from coach.taxonomy import TASK_TYPES, validate as validate_tags

    if "tags" in updates:
        updates["tags"] = validate_tags(updates["tags"])
    if "parts" in updates:
        updates["parts"] = validate_parts(updates["parts"])
    if "task_type" in updates and updates["task_type"] not in TASK_TYPES:
        raise ValueError(f"Unknown task_type: {updates['task_type']!r}.")
    if "delivery" in updates:
        updates["delivery"] = str(updates["delivery"] or "block").strip().lower() or "block"
        if updates["delivery"] not in DELIVERIES:
            raise ValueError(
                f"Unknown delivery: {updates['delivery']!r}. Expected one of: {', '.join(DELIVERIES)}."
            )
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
        if "parts" in updates:
            model.parts_json = serialize_parts(updates["parts"])
        if "is_public" in updates:
            model.is_public = 1 if updates["is_public"] else 0
        if "context_notes" in updates:
            model.context_notes = str(updates["context_notes"] or "").strip()[:2000]
        if "tags" in updates:
            model.tags_json = serialize_tags(updates["tags"])
        if "task_type" in updates:
            model.task_type = updates["task_type"]
        if "delivery" in updates:
            model.delivery = updates["delivery"]
        if "language" in updates:
            model.language = normalize_language(updates["language"])
        if "version_index" in updates:
            model.version_index = max(1, int(updates["version_index"] or 1))
        if "depends_on_task_id" in updates:
            model.depends_on_task_id = str(updates["depends_on_task_id"] or "").strip() or None
        if "version_root_id" in updates:
            model.version_root_id = str(updates["version_root_id"] or "").strip() or None
        if "owner" in updates:
            model.owner = str(updates["owner"]).strip()
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
    used so rows stay unique under ``uq_session_steps``. Admin
    aggregation is by candidate, so a step without a real episode is still counted.
    ``hints_used`` is accepted for legacy callers but always stored as ``[]``.
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


def _list_tasks(
    owner: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """List tasks newest last with per-task attempt counts (shared helper).

    Used by the admin UI (all tasks) and the curator UI (one owner's tasks).
    """
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


def list_tasks_for_owner(
    owner: str,
    q: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """List one owner's tasks for the curator UI (with attempt counts)."""
    return _list_tasks(owner=owner, q=q, limit=limit)


def merge_version_chain(
    root_id: str,
    *,
    delete_originals: bool = False,
) -> Optional[dict]:
    """Merge a version chain into one ``delivery='phased'`` task (migration).

    Collects ``root_id`` plus every successor whose ``version_root_id`` or
    ``depends_on_task_id`` resolves to the chain root, orders them by
    ``version_index``, and creates a phased task whose parts are the versions
    in order. Each phase keeps the version's prompt, scaffold, tags,
    ``max_score`` and ``difficulty``; ``pass_score`` defaults via
    ``default_pass_score``.

    ``delete_originals`` removes the source rows afterwards (their recorded
    steps cascade — pass ``False`` to keep history). Returns the new task, or
    ``None`` when the chain has fewer than two versions.
    """
    root = get_task(root_id)
    if root is None:
        return None
    chain_root = root.get("version_root_id") or root.get("id")
    versions = [
        t for t in _list_tasks(limit=500)
        if (t.get("version_root_id") or t.get("id")) == chain_root
    ]
    versions.sort(key=lambda t: (t.get("version_index") or 1, t.get("created_at") or ""))
    if len(versions) < 2:
        return None

    parts = []
    for i, t in enumerate(versions):
        part = {
            "key": t["id"],
            "prompt": t["prompt"],
            "tags": t.get("tags") or {"primary": "python", "secondary": []},
            "max_score": int(t.get("max_score") or 5),
            "difficulty": int(t.get("difficulty") or 2),
            "pass_score": default_pass_score(int(t.get("max_score") or 5)),
        }
        if t.get("scaffold"):
            part["scaffold"] = t["scaffold"]
        parts.append(part)

    merged = create_task(
        prompt=root.get("prompt") or "",
        owner=root.get("owner") or SYSTEM_OWNER,
        difficulty=max(int(v.get("difficulty") or 2) for v in versions),
        max_score=sum(int(v.get("max_score") or 5) for v in versions),
        source=root.get("source") or "user",
        is_public=bool(root.get("is_public")),
        context_notes=root.get("context_notes") or None,
        tags=root.get("tags"),
        task_type=root.get("task_type") or "implement",
        language=root.get("language"),
        parts=parts,
        delivery="phased",
    )
    if delete_originals:
        for t in versions:
            delete_task(t["id"])
    return merged


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