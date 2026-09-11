"""Evidence: immutable observation records, assessment, and SQL persistence."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from learner.graph import utcnow
from learner.types import LearnerNotFoundError, NodeNotFoundError, DuplicateEvidenceError
from learner.interfaces import EvidenceRepository, KnowledgeGraphRepository, LearnerModelRepository
from sqlalchemy import (
    func,
    select,
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Session, Mapped, mapped_column
from coach.db import aware_utc, naive_utc, uid, Base


class EvidenceType(str, Enum):
    """What kind of learner interaction produced the observation."""

    ANSWER = "answer"
    EXPLANATION = "explanation"
    CODE = "code"
    DEBUGGING = "debugging"
    PREDICTION = "prediction"
    TRACE = "trace"
    TEACH_BACK = "teach_back"
    SELF_REPORT = "self_report"
    CONVERSATION = "conversation"


class ObservationStatus(str, Enum):
    """How the observation was judged."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIALLY_CORRECT = "partially_correct"
    NOT_OBSERVED = "not_observed"
    AMBIGUOUS = "ambiguous"


class Evidence(BaseModel):
    """An immutable observation of learner performance on a knowledge node.

    ``frozen=True`` makes the model itself read-only after construction; the
    repository is additionally append-only (no update/delete). Corrections are
    recorded as new (superseding) evidence records, never by editing history.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    learner_id: uuid.UUID
    node_id: uuid.UUID
    evidence_type: EvidenceType
    observation_status: ObservationStatus
    correctness: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reasoning_quality: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    independence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    observed_behavior: Optional[str] = None
    assessor_explanation: Optional[str] = None
    assessment_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _not_observed_has_no_correctness(self) -> "Evidence":
        """Enforce the core rule: a not-observed record cannot be scored wrong."""
        if (
            self.observation_status == ObservationStatus.NOT_OBSERVED
            and self.correctness is not None
        ):
            raise ValueError("not_observed evidence must not carry a correctness score")
        return self

    # -- status helpers --------------------------------------------------

    def is_correct(self) -> bool:
        return self.observation_status == ObservationStatus.CORRECT

    def is_incorrect(self) -> bool:
        return self.observation_status == ObservationStatus.INCORRECT

    def is_partially_correct(self) -> bool:
        return self.observation_status == ObservationStatus.PARTIALLY_CORRECT

    def is_not_observed(self) -> bool:
        return self.observation_status == ObservationStatus.NOT_OBSERVED

    def is_ambiguous(self) -> bool:
        return self.observation_status == ObservationStatus.AMBIGUOUS


class EvidenceFilter(BaseModel):
    """Query filters for listing/counting evidence."""

    model_config = ConfigDict(extra="forbid")

    learner_id: Optional[uuid.UUID] = None
    node_id: Optional[uuid.UUID] = None
    evidence_type: Optional[EvidenceType] = None
    observation_status: Optional[ObservationStatus] = None
    from_time: Optional[datetime] = None
    to_time: Optional[datetime] = None


class EvidenceSummary(BaseModel):
    """Aggregated evidence summary for a (learner, node) pair.

    ``not_observed`` records are counted separately and never contribute to
    ``incorrect_count`` or to the correctness averages.
    """

    model_config = ConfigDict(extra="forbid")

    learner_id: uuid.UUID
    node_id: uuid.UUID
    observation_count: int
    correct_count: int
    incorrect_count: int
    partial_count: int
    ambiguous_count: int
    not_observed_count: int
    average_correctness: Optional[float] = None
    average_reasoning_quality: Optional[float] = None
    latest_observation: Optional[Evidence] = None
    latest_confidence: Optional[float] = None

class EvidenceService:
    def __init__(
        self,
        evidence_repository: EvidenceRepository,
        learner_repository: LearnerModelRepository,
        knowledge_repository: KnowledgeGraphRepository,
    ) -> None:
        self.evidence_repository = evidence_repository
        self.learner_repository = learner_repository
        self.knowledge_repository = knowledge_repository

    # -- write (append-only) ---------------------------------------------

    def add_evidence(self, evidence: Evidence) -> Evidence:
        """Append an immutable evidence record.

        Raises LearnerNotFoundError / NodeNotFoundError if the referenced
        learner or node does not exist. There is no edit or delete path.
        """
        if self.learner_repository.get_learner(evidence.learner_id) is None:
            raise LearnerNotFoundError(evidence.learner_id)
        if self.knowledge_repository.get_node(evidence.node_id) is None:
            raise NodeNotFoundError(evidence.node_id)
        return self.evidence_repository.add_evidence(evidence)

    # -- reads ------------------------------------------------------------

    def get_evidence(self, evidence_id: uuid.UUID) -> Evidence | None:
        return self.evidence_repository.get_evidence(evidence_id)

    def list_evidence_for_learner(
        self, learner_id: uuid.UUID, filters: Optional[EvidenceFilter] = None
    ) -> list[Evidence]:
        return self.evidence_repository.list_evidence_for_learner(learner_id, filters)

    def list_evidence_for_node(
        self, node_id: uuid.UUID, filters: Optional[EvidenceFilter] = None
    ) -> list[Evidence]:
        return self.evidence_repository.list_evidence_for_node(node_id, filters)

    def count_evidence(self, filters: Optional[EvidenceFilter] = None) -> int:
        return self.evidence_repository.count_evidence(filters)

    def get_latest_evidence(
        self, filters: Optional[EvidenceFilter] = None
    ) -> Evidence | None:
        return self.evidence_repository.get_latest_evidence(filters)

    # -- aggregation -------------------------------------------------------

    def summarize(self, learner_id: uuid.UUID, node_id: uuid.UUID) -> EvidenceSummary:
        """Aggregate all evidence for a (learner, node) pair.

        Never mutates the learner model. ``not_observed`` records are counted
        separately and excluded from the correctness averages — they are never
        treated as incorrect.
        """
        records = self.evidence_repository.list_evidence(
            EvidenceFilter(learner_id=learner_id, node_id=node_id)
        )
        if not records:
            return EvidenceSummary(
                learner_id=learner_id,
                node_id=node_id,
                observation_count=0,
                correct_count=0,
                incorrect_count=0,
                partial_count=0,
                ambiguous_count=0,
                not_observed_count=0,
            )

        correct = sum(1 for r in records if r.is_correct())
        incorrect = sum(1 for r in records if r.is_incorrect())
        partial = sum(1 for r in records if r.is_partially_correct())
        ambiguous = sum(1 for r in records if r.is_ambiguous())
        not_observed = sum(1 for r in records if r.is_not_observed())

        correctness = [r.correctness for r in records if r.correctness is not None]
        reasoning = [r.reasoning_quality for r in records if r.reasoning_quality is not None]
        avg_correctness = sum(correctness) / len(correctness) if correctness else None
        avg_reasoning = sum(reasoning) / len(reasoning) if reasoning else None

        latest = records[-1]  # repo returns chronologically ordered
        latest_confidence = next(
            (r.confidence for r in reversed(records) if r.confidence is not None), None
        )

        return EvidenceSummary(
            learner_id=learner_id,
            node_id=node_id,
            observation_count=len(records),
            correct_count=correct,
            incorrect_count=incorrect,
            partial_count=partial,
            ambiguous_count=ambiguous,
            not_observed_count=not_observed,
            average_correctness=avg_correctness,
            average_reasoning_quality=avg_reasoning,
            latest_observation=latest,
            latest_confidence=latest_confidence,
        )

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

class EvidenceModel(Base):
    """Immutable, append-only learner evidence. No update/delete operations."""

    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_learner", "learner_id"),
        Index("ix_evidence_node", "node_id"),
        Index("ix_evidence_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learners.id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    correctness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reasoning_quality: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    independence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_behavior: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assessor_explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assessment_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
