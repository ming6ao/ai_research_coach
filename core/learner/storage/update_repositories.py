"""SQLAlchemy implementations for misconceptions and the frontier.

Misconception evidence links live on the ``learner_misconceptions.metadata``
JSON blob (a ``evidence_links`` list) — the join table was dropped.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.frontier import FrontierStatus, LearnerFrontier
from ..domain.misconception import (
    EvidenceRelationship,
    LearnerMisconception,
    MisconceptionEvidenceLink,
    MisconceptionStatus,
)
from .converters import aware_utc, naive_utc, uid
from .models import (
    LearnerFrontierModel,
    LearnerMisconceptionModel,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SQLLearnerMisconceptionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, misconception: LearnerMisconception) -> LearnerMisconception:
        model = self._session.scalar(
            select(LearnerMisconceptionModel).where(
                LearnerMisconceptionModel.id == uid(misconception.id)
            )
        )
        now = _now()
        if model is None:
            model = LearnerMisconceptionModel(
                id=uid(misconception.id),
                learner_id=uid(misconception.learner_id),
                misconception_node_id=uid(misconception.misconception_node_id),
                confidence=misconception.confidence,
                status=misconception.status.value,
                first_detected_at=naive_utc(misconception.first_detected_at),
                last_observed_at=naive_utc(misconception.last_observed_at),
                resolved_at=naive_utc(misconception.resolved_at) if misconception.resolved_at else None,
                notes=misconception.notes,
                meta=misconception.metadata,
            )
            self._session.add(model)
        else:
            model.confidence = misconception.confidence
            model.status = misconception.status.value
            model.last_observed_at = naive_utc(misconception.last_observed_at)
            model.resolved_at = naive_utc(misconception.resolved_at) if misconception.resolved_at else None
            model.notes = misconception.notes
            model.meta = misconception.metadata
        self._session.commit()
        return self.get(misconception.id)

    def get(self, misconception_id: uuid.UUID) -> LearnerMisconception | None:
        model = self._session.get(LearnerMisconceptionModel, uid(misconception_id))
        return self._to_mc(model) if model else None

    def list_for_learner(self, learner_id: uuid.UUID) -> list[LearnerMisconception]:
        models = self._session.scalars(
            select(LearnerMisconceptionModel)
            .where(LearnerMisconceptionModel.learner_id == uid(learner_id))
            .order_by(LearnerMisconceptionModel.first_detected_at)
        ).all()
        return [self._to_mc(m) for m in models]

    def list_evidence_links(
        self, misconception_id: uuid.UUID
    ) -> list[MisconceptionEvidenceLink]:
        model = self._session.get(LearnerMisconceptionModel, uid(misconception_id))
        if model is None:
            return []
        meta = dict(model.meta or {})
        links = []
        for item in meta.get("evidence_links") or []:
            created = datetime.fromisoformat(item["created_at"])
            links.append(
                MisconceptionEvidenceLink(
                    id=uuid.uuid4(),
                    misconception_id=uuid.UUID(model.id),
                    evidence_id=uuid.UUID(item["evidence_id"]),
                    relationship=EvidenceRelationship(item["relationship"]),
                    created_at=aware_utc(created),
                )
            )
        return links

    @staticmethod
    def _to_mc(model: LearnerMisconceptionModel) -> LearnerMisconception:
        return LearnerMisconception(
            id=uuid.UUID(model.id),
            learner_id=uuid.UUID(model.learner_id),
            misconception_node_id=uuid.UUID(model.misconception_node_id),
            confidence=model.confidence,
            status=MisconceptionStatus(model.status),
            first_detected_at=aware_utc(model.first_detected_at),
            last_observed_at=aware_utc(model.last_observed_at),
            resolved_at=aware_utc(model.resolved_at),
            notes=model.notes,
            metadata=dict(model.meta or {}),
        )


class SQLFrontierRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, entry: LearnerFrontier) -> LearnerFrontier:
        model = self._session.scalar(
            select(LearnerFrontierModel).where(
                LearnerFrontierModel.learner_id == uid(entry.learner_id),
                LearnerFrontierModel.node_id == uid(entry.node_id),
            )
        )
        now = _now()
        if model is None:
            model = LearnerFrontierModel(
                id=uid(entry.id),
                learner_id=uid(entry.learner_id),
                node_id=uid(entry.node_id),
                priority=entry.priority,
                reason=entry.reason,
                source_node_id=uid(entry.source_node_id) if entry.source_node_id else None,
                status=entry.status.value,
                created_at=naive_utc(entry.created_at),
                updated_at=naive_utc(now),
            )
            self._session.add(model)
        else:
            model.priority = entry.priority
            model.reason = entry.reason
            model.source_node_id = uid(entry.source_node_id) if entry.source_node_id else None
            model.status = entry.status.value
            model.updated_at = naive_utc(now)
        self._session.commit()
        return self.get(entry.learner_id, entry.node_id)

    def get(
        self, learner_id: uuid.UUID, node_id: uuid.UUID
    ) -> LearnerFrontier | None:
        model = self._session.scalar(
            select(LearnerFrontierModel).where(
                LearnerFrontierModel.learner_id == uid(learner_id),
                LearnerFrontierModel.node_id == uid(node_id),
            )
        )
        return self._to_entry(model) if model else None

    def list_for_learner(self, learner_id: uuid.UUID) -> list[LearnerFrontier]:
        models = self._session.scalars(
            select(LearnerFrontierModel)
            .where(LearnerFrontierModel.learner_id == uid(learner_id))
            .order_by(LearnerFrontierModel.priority.desc())
        ).all()
        return [self._to_entry(m) for m in models]

    def delete(self, learner_id: uuid.UUID, node_id: uuid.UUID) -> bool:
        model = self._session.scalar(
            select(LearnerFrontierModel).where(
                LearnerFrontierModel.learner_id == uid(learner_id),
                LearnerFrontierModel.node_id == uid(node_id),
            )
        )
        if model is None:
            return False
        self._session.delete(model)
        self._session.commit()
        return True

    @staticmethod
    def _to_entry(model: LearnerFrontierModel) -> LearnerFrontier:
        return LearnerFrontier(
            id=uuid.UUID(model.id),
            learner_id=uuid.UUID(model.learner_id),
            node_id=uuid.UUID(model.node_id),
            priority=model.priority,
            reason=model.reason,
            source_node_id=uuid.UUID(model.source_node_id) if model.source_node_id else None,
            status=FrontierStatus(model.status),
            created_at=aware_utc(model.created_at),
            updated_at=aware_utc(model.updated_at),
        )