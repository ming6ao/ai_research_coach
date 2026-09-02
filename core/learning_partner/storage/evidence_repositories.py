"""SQLAlchemy implementation of the EvidenceRepository boundary.

Append-only by construction: only ``add_evidence`` writes rows. There is no
update or delete path for evidence. Aggregation of evidence into learner-model
estimates happens in the service/domain layer, never in SQL.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.errors import DuplicateEvidenceError
from ..domain.evidence import Evidence, EvidenceFilter, EvidenceType, ObservationStatus
from .converters import aware_utc, naive_utc, uid
from .models import EvidenceModel


class SQLEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # -- write -----------------------------------------------------------

    def add_evidence(self, evidence: Evidence) -> Evidence:
        """Append a new evidence record. Returns the stored record."""
        if self.get_evidence(evidence.id) is not None:
            raise DuplicateEvidenceError(evidence.id)
        model = EvidenceModel(
            id=uid(evidence.id),
            learner_id=uid(evidence.learner_id),
            session_id=uid(evidence.session_id) if evidence.session_id else None,
            interaction_id=uid(evidence.interaction_id) if evidence.interaction_id else None,
            assessment_task_id=uid(evidence.assessment_task_id) if evidence.assessment_task_id else None,
            node_id=uid(evidence.node_id),
            evidence_type=evidence.evidence_type.value,
            observation_status=evidence.observation_status.value,
            correctness=evidence.correctness,
            reasoning_quality=evidence.reasoning_quality,
            independence=evidence.independence,
            confidence=evidence.confidence,
            observed_behavior=evidence.observed_behavior,
            assessor_explanation=evidence.assessor_explanation,
            assessment_payload=evidence.assessment_payload,
            created_at=naive_utc(evidence.created_at),
        )
        self._session.add(model)
        self._session.commit()
        return self.get_evidence(evidence.id)

    # -- reads ------------------------------------------------------------

    def get_evidence(self, evidence_id: uuid.UUID) -> Evidence | None:
        model = self._session.get(EvidenceModel, uid(evidence_id))
        return self._to_evidence(model) if model else None

    def list_evidence(
        self, filters: Optional[EvidenceFilter] = None
    ) -> list[Evidence]:
        stmt = select(EvidenceModel)
        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(EvidenceModel.created_at, EvidenceModel.id)
        models = self._session.scalars(stmt).all()
        return [self._to_evidence(m) for m in models]

    def list_evidence_for_learner(
        self, learner_id: uuid.UUID, filters: Optional[EvidenceFilter] = None
    ) -> list[Evidence]:
        merged = self._merge(filters, learner_id=learner_id)
        return self.list_evidence(merged)

    def list_evidence_for_node(
        self, node_id: uuid.UUID, filters: Optional[EvidenceFilter] = None
    ) -> list[Evidence]:
        merged = self._merge(filters, node_id=node_id)
        return self.list_evidence(merged)

    def list_evidence_for_interaction(
        self, interaction_id: uuid.UUID, filters: Optional[EvidenceFilter] = None
    ) -> list[Evidence]:
        stmt = select(EvidenceModel)
        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.where(EvidenceModel.interaction_id == uid(interaction_id))
        stmt = stmt.order_by(EvidenceModel.created_at, EvidenceModel.id)
        models = self._session.scalars(stmt).all()
        return [self._to_evidence(m) for m in models]

    def count_evidence(self, filters: Optional[EvidenceFilter] = None) -> int:
        stmt = select(func.count(EvidenceModel.id))
        stmt = self._apply_filters(stmt, filters)
        return self._session.scalar(stmt) or 0

    def get_latest_evidence(
        self, filters: Optional[EvidenceFilter] = None
    ) -> Evidence | None:
        stmt = select(EvidenceModel)
        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(EvidenceModel.created_at.desc(), EvidenceModel.id.desc())
        model = self._session.scalars(stmt).first()
        return self._to_evidence(model) if model else None

    # -- helpers ---------------------------------------------------------

    def _merge(
        self, filters: Optional[EvidenceFilter], **required
    ) -> EvidenceFilter:
        data = filters.model_dump(exclude_none=True) if filters else {}
        data.update({k: v for k, v in required.items() if v is not None})
        return EvidenceFilter(**data)

    def _apply_filters(self, stmt, filters: Optional[EvidenceFilter]):
        if filters is None:
            return stmt
        if filters.learner_id is not None:
            stmt = stmt.where(EvidenceModel.learner_id == uid(filters.learner_id))
        if filters.node_id is not None:
            stmt = stmt.where(EvidenceModel.node_id == uid(filters.node_id))
        if filters.evidence_type is not None:
            stmt = stmt.where(EvidenceModel.evidence_type == filters.evidence_type.value)
        if filters.observation_status is not None:
            stmt = stmt.where(
                EvidenceModel.observation_status == filters.observation_status.value
            )
        if filters.from_time is not None:
            stmt = stmt.where(EvidenceModel.created_at >= naive_utc(filters.from_time))
        if filters.to_time is not None:
            stmt = stmt.where(EvidenceModel.created_at <= naive_utc(filters.to_time))
        return stmt

    @staticmethod
    def _to_evidence(model: EvidenceModel) -> Evidence:
        return Evidence(
            id=uuid.UUID(model.id),
            learner_id=uuid.UUID(model.learner_id),
            session_id=uuid.UUID(model.session_id) if model.session_id else None,
            interaction_id=uuid.UUID(model.interaction_id) if model.interaction_id else None,
            assessment_task_id=uuid.UUID(model.assessment_task_id) if model.assessment_task_id else None,
            node_id=uuid.UUID(model.node_id),
            evidence_type=EvidenceType(model.evidence_type),
            observation_status=ObservationStatus(model.observation_status),
            correctness=model.correctness,
            reasoning_quality=model.reasoning_quality,
            independence=model.independence,
            confidence=model.confidence,
            observed_behavior=model.observed_behavior,
            assessor_explanation=model.assessor_explanation,
            assessment_payload=dict(model.assessment_payload or {}),
            created_at=aware_utc(model.created_at),
        )