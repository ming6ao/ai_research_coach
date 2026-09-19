"""DB-backed custom leaf skills layered on the built-in taxonomy.

The built-in vocabulary lives in ``coach/taxonomy.py`` (code). Curators may
add new **leaf skills** under an existing area; those are stored here (one row
per skill) and merged into the live taxonomy at startup (and on demand) so
tags, beliefs, mastery folding, and the picker treat them exactly like
built-in leaves.

Only leaf skills are user-extensible — domains and areas stay fixed, because
every area has a built-in parent domain and the hierarchy is what beliefs fold
over. A custom skill always belongs to exactly one known area.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, mapped_column

from coach.db import Base


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CustomSkillModel(Base):
    """One curator-added leaf skill attached to a built-in area."""

    __tablename__ = "custom_skills"

    skill: Mapped[str] = mapped_column(String(64), primary_key=True)
    area: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


# DB path whose custom skills are currently merged into the taxonomy. Lets a
# repeated ``reload_into_taxonomy`` be a cheap no-op while still reacting when
# tests swap ``coach.db.DB_PATH``.
_loaded_path: Optional[str] = None


def _rows_from_db() -> list[tuple[str, str]]:
    from coach.db import learner_session

    session = learner_session()
    try:
        return [
            (m.skill, m.area)
            for m in session.scalars(select(CustomSkillModel)).all()
        ]
    finally:
        session.close()


def reload_into_taxonomy(*, force: bool = False) -> None:
    """Merge the active DB's custom skills into the live taxonomy.

    Best-effort and idempotent: a missing table (before schema creation) is
    ignored, and a repeated call for the same DB path is a no-op unless
    ``force`` is set.
    """
    global _loaded_path
    from coach import db as _db
    from coach.taxonomy import load_custom_skills

    path = str(_db.DB_PATH)
    if not force and path == _loaded_path:
        return
    try:
        rows = _rows_from_db()
    except Exception:
        return  # table not created yet — retried after DDL
    load_custom_skills(rows)
    _loaded_path = path


def create_custom_skill(skill: str, area: str, created_by: str = "") -> dict:
    """Register a new leaf skill under ``area`` and persist it.

    Validates and merges the skill into the live taxonomy first; the DB row is
    then written. The taxonomy change is rolled back if the insert fails.
    """
    from coach.db import create_schema, learner_session
    from coach.taxonomy import area_of, domain_of, register_custom_skill, unregister_custom_skill

    create_schema()
    canon = register_custom_skill(skill, area)
    try:
        session = learner_session()
        try:
            if session.get(CustomSkillModel, canon) is None:
                session.add(
                    CustomSkillModel(
                        skill=canon,
                        area=area_of(canon) or area,
                        created_by=(created_by or "").strip() or None,
                        created_at=_utcnow_naive(),
                    )
                )
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    except Exception:
        # Only roll back a brand-new node; a pre-existing row stays registered.
        unregister_custom_skill(canon)
        raise
    return {"skill": canon, "area": area_of(canon), "domain": domain_of(canon)}


def list_custom_skills() -> list[dict]:
    """All registered custom skills, newest first."""
    from coach.db import create_schema, learner_session

    create_schema()
    session = learner_session()
    try:
        rows = session.scalars(
            select(CustomSkillModel).order_by(CustomSkillModel.created_at.desc())
        ).all()
        return [
            {
                "skill": m.skill,
                "area": m.area,
                "created_by": m.created_by or "",
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
            for m in rows
        ]
    finally:
        session.close()


def delete_custom_skill(skill: str) -> bool:
    """Delete a custom skill row and unregister it from the live taxonomy."""
    from coach.db import create_schema, learner_session
    from coach.taxonomy import is_custom_skill, resolve_node, unregister_custom_skill

    create_schema()
    canon = resolve_node(skill)
    if canon is None or not is_custom_skill(canon):
        return False
    session = learner_session()
    try:
        model = session.get(CustomSkillModel, canon)
        if model is None:
            return False
        session.delete(model)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    unregister_custom_skill(canon)
    return True
