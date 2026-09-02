"""SQLAlchemy implementation of the LearnerModelRepository boundary.

Pure persistence. Learner-model semantics (lazy initialization, status
derivation, unknown-vs-low-mastery) live in the service/domain layer, not here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.learner import Learner, LearnerKnowledgeState, StateStatus
from .converters import aware_utc, naive_utc, uid
from .models import LearnerKnowledgeStateModel, LearnerModel


class SQLLearnerModelRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # -- learners --------------------------------------------------------

    def create_learner(self, learner: Learner) -> Learner:
        model = LearnerModel(
            id=uid(learner.id),
            meta=learner.metadata,
            created_at=naive_utc(learner.created_at),
            updated_at=naive_utc(learner.updated_at),
        )
        self._session.add(model)
        self._session.commit()
        return self.get_learner(learner.id)

    def get_learner(self, learner_id: uuid.UUID) -> Learner | None:
        model = self._session.get(LearnerModel, uid(learner_id))
        return self._to_learner(model) if model else None

    # -- states ----------------------------------------------------------

    def get_state(
        self, learner_id: uuid.UUID, node_id: uuid.UUID
    ) -> LearnerKnowledgeState | None:
        model = self._session.scalar(
            select(LearnerKnowledgeStateModel).where(
                LearnerKnowledgeStateModel.learner_id == uid(learner_id),
                LearnerKnowledgeStateModel.node_id == uid(node_id),
            )
        )
        return self._to_state(model) if model else None

    def save_state(self, state: LearnerKnowledgeState) -> LearnerKnowledgeState:
        """Insert or update the state for (learner, node). Unique on that pair."""
        model = self._session.scalar(
            select(LearnerKnowledgeStateModel).where(
                LearnerKnowledgeStateModel.learner_id == uid(state.learner_id),
                LearnerKnowledgeStateModel.node_id == uid(state.node_id),
            )
        )
        now = datetime.now(timezone.utc)

        if model is None:
            model = LearnerKnowledgeStateModel(
                id=uid(uuid.uuid4()),
                learner_id=uid(state.learner_id),
                node_id=uid(state.node_id),
                mastery=state.mastery,
                uncertainty=state.uncertainty,
                conceptual=state.conceptual,
                procedural=state.procedural,
                implementation=state.implementation,
                transfer=state.transfer,
                fluency=state.fluency,
                self_confidence=state.self_confidence,
                reasoning=state.reasoning,
                evidence_count=state.evidence_count,
                last_assessed_at=naive_utc(state.last_assessed_at) if state.last_assessed_at else None,
                last_decay_at=naive_utc(state.last_decay_at) if state.last_decay_at else None,
                status=state.status.value,
                meta=state.metadata,
                created_at=naive_utc(state.created_at),
                updated_at=naive_utc(state.updated_at),
            )
            self._session.add(model)
        else:
            model.mastery = state.mastery
            model.uncertainty = state.uncertainty
            model.conceptual = state.conceptual
            model.procedural = state.procedural
            model.implementation = state.implementation
            model.transfer = state.transfer
            model.fluency = state.fluency
            model.self_confidence = state.self_confidence
            model.reasoning = state.reasoning
            model.evidence_count = state.evidence_count
            model.last_assessed_at = naive_utc(state.last_assessed_at) if state.last_assessed_at else None
            model.last_decay_at = naive_utc(state.last_decay_at) if state.last_decay_at else None
            model.status = state.status.value
            model.meta = state.metadata
            model.updated_at = naive_utc(now)

        self._session.commit()
        return self.get_state(state.learner_id, state.node_id)

    def list_learner_states(self, learner_id: uuid.UUID) -> list[LearnerKnowledgeState]:
        models = self._session.scalars(
            select(LearnerKnowledgeStateModel)
            .where(LearnerKnowledgeStateModel.learner_id == uid(learner_id))
            .order_by(LearnerKnowledgeStateModel.node_id)
        ).all()
        return [self._to_state(m) for m in models]

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _to_learner(model: LearnerModel) -> Learner:
        return Learner(
            id=uuid.UUID(model.id),
            metadata=dict(model.meta or {}),
            created_at=aware_utc(model.created_at),
            updated_at=aware_utc(model.updated_at),
        )

    @staticmethod
    def _to_state(model: LearnerKnowledgeStateModel) -> LearnerKnowledgeState:
        return LearnerKnowledgeState(
            learner_id=uuid.UUID(model.learner_id),
            node_id=uuid.UUID(model.node_id),
            mastery=model.mastery,
            uncertainty=model.uncertainty,
            conceptual=model.conceptual,
            procedural=model.procedural,
            implementation=model.implementation,
            transfer=model.transfer,
            fluency=model.fluency,
            self_confidence=model.self_confidence,
            reasoning=model.reasoning,
            evidence_count=model.evidence_count,
            last_assessed_at=aware_utc(model.last_assessed_at),
            last_decay_at=aware_utc(model.last_decay_at),
            status=StateStatus(model.status),
            metadata=dict(model.meta or {}),
            created_at=aware_utc(model.created_at),
            updated_at=aware_utc(model.updated_at),
        )