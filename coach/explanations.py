"""Selection-driven explanations (``explanations``).

A learner can highlight a passage in the coaching conversation and ask for an
explanation. One row per request/response. These rows are **not** scored
transitions: they never enter ``session_steps`` and never update the belief
system. They exist so the right-hand panel can be restored on resume/review,
so identical selections are cached (no repeated LLM call), and so curation can
see where learners get stuck.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from coach.db import Base, learner_session


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ExplanationModel(Base):
    __tablename__ = "explanations"
    __table_args__ = (
        Index("ix_explanations_session", "session_id"),
        Index("ix_explanations_candidate", "candidate"),
        Index("ix_explanations_task", "task_id"),
        Index("ix_explanations_hash", "session_id", "request_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate: Mapped[str] = mapped_column(String(255), nullable=False)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    step_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phase_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    selected_text: Mapped[str] = mapped_column(Text, nullable=False)
    context_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    related_terms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def parse_related_terms(raw: Optional[str]) -> list[str]:
    """Tolerant parse of the stored ``related_terms_json`` list."""
    try:
        parsed = json.loads(raw or "[]")
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(t) for t in parsed if str(t).strip()]


def explanation_to_dict(m: ExplanationModel) -> dict:
    return {
        "id": m.id,
        "session_id": m.session_id,
        "task_id": m.task_id,
        "step_key": m.step_key,
        "phase_index": m.phase_index,
        "source_kind": m.source_kind or "other",
        "selected_text": m.selected_text or "",
        "context": m.context_text or "",
        "question": m.question,
        "parent_id": m.parent_id,
        "title": m.title or "",
        "explanation": m.explanation or "",
        "related_terms": parse_related_terms(m.related_terms_json),
        "model": m.model or "",
        "status": m.status or "ok",
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def insert_explanation(
    session_id: str,
    candidate: str,
    *,
    task_id: Optional[str] = None,
    step_key: Optional[str] = None,
    phase_index: Optional[int] = None,
    source_kind: str = "other",
    selected_text: str = "",
    context_text: str = "",
    question: Optional[str] = None,
    parent_id: Optional[str] = None,
    request_hash: str = "",
    title: str = "",
    explanation: str = "",
    related_terms: Optional[list] = None,
    model: str = "",
    status: str = "ok",
) -> dict:
    """Persist one explanation row and return its dict form."""
    from coach.db import create_schema

    create_schema()
    row = ExplanationModel(
        id=str(uuid.uuid4()),
        session_id=session_id,
        candidate=candidate,
        task_id=task_id,
        step_key=step_key,
        phase_index=phase_index,
        source_kind=(source_kind or "other")[:16],
        selected_text=selected_text or "",
        context_text=context_text or "",
        question=(question or None),
        parent_id=parent_id,
        request_hash=request_hash or "",
        title=(title or "")[:500],
        explanation=explanation or "",
        related_terms_json=json.dumps(list(related_terms or [])[:10]),
        model=(model or "")[:64],
        status=status or "ok",
        created_at=_utcnow_naive(),
    )
    session = learner_session()
    try:
        session.add(row)
        session.commit()
        return explanation_to_dict(row)
    finally:
        session.close()


def find_cached(session_id: str, request_hash: str) -> Optional[dict]:
    """Return a successful explanation for an identical request, if stored."""
    if not request_hash:
        return None
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        m = session.scalars(
            select(ExplanationModel)
            .where(
                ExplanationModel.session_id == session_id,
                ExplanationModel.request_hash == request_hash,
                ExplanationModel.status == "ok",
            )
            .order_by(ExplanationModel.created_at.desc())
            .limit(1)
        ).first()
        return explanation_to_dict(m) if m else None
    finally:
        session.close()


def get_explanation(explanation_id: str) -> Optional[dict]:
    """Fetch one row by id (used to ground follow-up questions)."""
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        m = session.get(ExplanationModel, explanation_id)
        return explanation_to_dict(m) if m else None
    finally:
        session.close()


def list_explanations(session_id: str) -> list[dict]:
    """All explanations for a session, oldest first."""
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        rows = session.scalars(
            select(ExplanationModel)
            .where(ExplanationModel.session_id == session_id)
            .order_by(ExplanationModel.created_at)
        ).all()
        return [explanation_to_dict(m) for m in rows]
    finally:
        session.close()


def delete_session_explanations(session_id: str) -> int:
    """Delete a session's explanation rows (session/data cleanup)."""
    from coach.db import create_schema

    create_schema()
    session = learner_session()
    try:
        n = (
            session.query(ExplanationModel)
            .filter(ExplanationModel.session_id == session_id)
            .delete(synchronize_session=False)
        )
        session.commit()
        return n or 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
