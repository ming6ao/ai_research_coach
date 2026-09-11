"""Learner model: learners, per-node mastery states, and SQL persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from learner.graph import utcnow
from learner.types import LearnerNotFoundError, NodeNotFoundError
from learner.interfaces import KnowledgeGraphRepository, LearnerModelRepository
from sqlalchemy import (
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, Mapped, mapped_column
from coach.db import aware_utc, naive_utc, uid, Base


# Neutral prior for an unseen node (see module docstring).
UNKNOWN_MASTERY = 0.5
UNKNOWN_UNCERTAINTY = 1.0
UNKNOWN_DIMENSION = 0.5

# Default status thresholds (configurable via domain.update.UpdateConfig).
UNCERTAINTY_THRESHOLD = 0.35
DEVELOPING_MASTERY = 0.70
PROFICIENT_MASTERY = 0.70
PROFICIENT_UNCERTAINTY = 0.25
MASTERED_MASTERY = 0.85
MASTERED_UNCERTAINTY = 0.15
# Strictly-below-neutral mastery counts as "low". Unknown (0.5) is never low.
LOW_MASTERY_THRESHOLD = UNKNOWN_MASTERY


class StateStatus(str, Enum):
    """Classification of what we believe about a learner on one node."""

    UNKNOWN = "unknown"
    UNCERTAIN = "uncertain"
    DEVELOPING = "developing"
    PROFICIENT = "proficient"
    MASTERED = "mastered"


class Learner(BaseModel):
    """A person being coached."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    candidate: Optional[str] = Field(default=None, description="Parent-app candidate id (email or guest-<hex>); unique.")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class LearnerKnowledgeState(BaseModel):
    """What we currently believe about one learner's ability on one knowledge node.

    All scores are in [0, 1]. ``mastery`` is the point-estimate belief;
    ``uncertainty`` is the spread of that belief (1.0 = maximum uncertainty).
    Competency dimensions (conceptual / procedural / implementation / transfer /
    fluency / self_confidence) are sub-scores along the same [0, 1] scale.
    """

    model_config = ConfigDict(extra="forbid")

    learner_id: uuid.UUID
    node_id: uuid.UUID

    mastery: float = Field(default=UNKNOWN_MASTERY, ge=0.0, le=1.0)
    uncertainty: float = Field(default=UNKNOWN_UNCERTAINTY, ge=0.0, le=1.0)

    conceptual: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    procedural: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    implementation: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    transfer: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    fluency: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    self_confidence: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    reasoning: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)

    evidence_count: int = Field(default=0, ge=0)
    last_assessed_at: datetime | None = None
    last_decay_at: datetime | None = None

    status: StateStatus = StateStatus.UNKNOWN
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _unknown_means_no_evidence(self) -> "LearnerKnowledgeState":
        """Enforce the core semantic rule: unknown is the neutral prior, not a score."""
        if self.status == StateStatus.UNKNOWN:
            if self.evidence_count != 0:
                raise ValueError("status 'unknown' requires evidence_count == 0")
            if self.mastery != UNKNOWN_MASTERY:
                raise ValueError(f"status 'unknown' requires mastery == {UNKNOWN_MASTERY}")
            if self.uncertainty != UNKNOWN_UNCERTAINTY:
                raise ValueError(f"status 'unknown' requires uncertainty == {UNKNOWN_UNCERTAINTY}")
        return self

    @staticmethod
    def derive_status(
        evidence_count: int, mastery: float, uncertainty: float, config: Any = None
    ) -> StateStatus:
        """Canonical status bucket for a given belief, in [0, 1] scores.

        ``config`` may be any object exposing the threshold attributes
        (e.g. ``domain.update.UpdateConfig``); defaults to the module constants.
        """
        if config is None:
            unc = UNCERTAINTY_THRESHOLD
            dev = DEVELOPING_MASTERY
            prof_m = PROFICIENT_MASTERY
            prof_u = PROFICIENT_UNCERTAINTY
            mast_m = MASTERED_MASTERY
            mast_u = MASTERED_UNCERTAINTY
        else:
            unc = config.uncertain_uncertainty
            dev = config.developing_mastery
            prof_m = config.proficient_mastery
            prof_u = config.proficient_uncertainty
            mast_m = config.mastered_mastery
            mast_u = config.mastered_uncertainty

        if evidence_count == 0:
            return StateStatus.UNKNOWN
        if uncertainty > unc:
            return StateStatus.UNCERTAIN
        if mastery >= mast_m and uncertainty <= mast_u:
            return StateStatus.MASTERED
        if mastery >= prof_m and uncertainty <= prof_u:
            return StateStatus.PROFICIENT
        return StateStatus.DEVELOPING

    # -- deterministic derived helpers -----------------------------------

    def is_unknown(self) -> bool:
        """No evidence has been observed for this node yet."""
        return self.status == StateStatus.UNKNOWN

    def is_uncertain(self) -> bool:
        """Belief is not confident: unknown, or uncertain even with some evidence."""
        return self.status in (StateStatus.UNKNOWN, StateStatus.UNCERTAIN)

    def is_low_mastery(self) -> bool:
        """Mastery is strictly below the neutral prior.

        Never true for an ``unknown`` state (whose mastery is exactly 0.5).
        """
        return self.mastery < LOW_MASTERY_THRESHOLD

    def is_mastered(self) -> bool:
        """Learner is believed to have mastered the node."""
        return self.status == StateStatus.MASTERED

    def is_ready_for_assessment(self) -> bool:
        """We should assess this node: the belief is not yet confident."""
        return self.is_unknown() or self.is_uncertain()

    def confidence_level(self) -> float:
        """Complement of uncertainty, in [0, 1]."""
        return 1.0 - self.uncertainty

class LearnerModelService:
    def __init__(
        self,
        learner_repository: LearnerModelRepository,
        knowledge_repository: KnowledgeGraphRepository,
    ) -> None:
        self._learners = learner_repository
        self._knowledge = knowledge_repository

    # -- learners ----------------------------------------------------------

    def create_learner(self, learner: Optional[Learner] = None) -> Learner:
        return self._learners.create_learner(learner or Learner())

    def get_learner(self, learner_id: uuid.UUID) -> Learner | None:
        return self._learners.get_learner(learner_id)

    # -- states -------------------------------------------------------------

    def get_state(
        self, learner_id: uuid.UUID, node_id: uuid.UUID
    ) -> LearnerKnowledgeState | None:
        """Return the persisted state, or None if the learner never encountered the node."""
        return self._learners.get_state(learner_id, node_id)

    def initialize_state(
        self, learner_id: uuid.UUID, node_id: uuid.UUID
    ) -> LearnerKnowledgeState:
        """Lazily create a neutral 'unknown' state for (learner, node).

        Idempotent: returns the existing state if one already exists. Does not
        create state for every node in the graph.
        """
        if self.get_learner(learner_id) is None:
            raise LearnerNotFoundError(learner_id)
        if self._knowledge.get_node(node_id) is None:
            raise NodeNotFoundError(node_id)

        existing = self.get_state(learner_id, node_id)
        if existing is not None:
            return existing

        now = utcnow()
        state = LearnerKnowledgeState(
            learner_id=learner_id,
            node_id=node_id,
            mastery=UNKNOWN_MASTERY,
            uncertainty=UNKNOWN_UNCERTAINTY,
            conceptual=UNKNOWN_DIMENSION,
            procedural=UNKNOWN_DIMENSION,
            implementation=UNKNOWN_DIMENSION,
            transfer=UNKNOWN_DIMENSION,
            fluency=UNKNOWN_DIMENSION,
            self_confidence=UNKNOWN_DIMENSION,
            reasoning=UNKNOWN_DIMENSION,
            evidence_count=0,
            status=StateStatus.UNKNOWN,
            created_at=now,
            updated_at=now,
        )
        return self._learners.save_state(state)

    def upsert_state(self, state: LearnerKnowledgeState) -> LearnerKnowledgeState:
        """Insert or update the state for (learner, node).

        Validates that the learner and node exist. The state's scores are
        persisted as provided; the caller (a later evidence stage) is
        responsible for deriving them from evidence.
        """
        if self.get_learner(state.learner_id) is None:
            raise LearnerNotFoundError(state.learner_id)
        if self._knowledge.get_node(state.node_id) is None:
            raise NodeNotFoundError(state.node_id)
        return self._learners.save_state(state)

    def list_learner_states(
        self, learner_id: uuid.UUID
    ) -> list[LearnerKnowledgeState]:
        return self._learners.list_learner_states(learner_id)

    # -- derived lists (semantics in Python, not SQL) -----------------------

    def list_uncertain_nodes(
        self, learner_id: uuid.UUID
    ) -> list[LearnerKnowledgeState]:
        """States where the belief is not confident (unknown or uncertain)."""
        return [s for s in self.list_learner_states(learner_id) if s.is_uncertain()]

    def list_low_mastery_nodes(
        self, learner_id: uuid.UUID
    ) -> list[LearnerKnowledgeState]:
        """States with mastery strictly below neutral. Unknown states are excluded."""
        return [s for s in self.list_learner_states(learner_id) if s.is_low_mastery()]

    def list_mastered_nodes(
        self, learner_id: uuid.UUID
    ) -> list[LearnerKnowledgeState]:
        """States classified as mastered."""
        return [s for s in self.list_learner_states(learner_id) if s.is_mastered()]

class SQLLearnerModelRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # -- learners --------------------------------------------------------

    def create_learner(self, learner: Learner) -> Learner:
        model = LearnerModel(
            id=uid(learner.id),
            candidate=learner.candidate,
            meta=learner.metadata,
            created_at=naive_utc(learner.created_at),
            updated_at=naive_utc(learner.updated_at),
        )
        self._session.add(model)
        try:
            self._session.commit()
        except IntegrityError:
            # Candidate already bound to a learner: reuse the existing row.
            self._session.rollback()
            existing = self.get_learner_by_candidate(learner.candidate)
            if existing is not None:
                return existing
            raise
        return self.get_learner(learner.id)

    def get_learner(self, learner_id: uuid.UUID) -> Learner | None:
        model = self._session.get(LearnerModel, uid(learner_id))
        return self._to_learner(model) if model else None

    def get_learner_by_candidate(self, candidate: str) -> Learner | None:
        model = self._session.scalar(
            select(LearnerModel).where(LearnerModel.candidate == candidate)
        )
        return self._to_learner(model) if model else None

    def update_candidate(self, learner_id: uuid.UUID, candidate: str) -> Learner | None:
        model = self._session.get(LearnerModel, uid(learner_id))
        if model is None:
            return None
        model.candidate = candidate
        model.updated_at = datetime.now(timezone.utc)
        self._session.commit()
        return self.get_learner(learner_id)

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
            candidate=model.candidate,
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

class LearnerModel(Base):
    __tablename__ = "learners"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LearnerKnowledgeStateModel(Base):
    __tablename__ = "learner_knowledge_states"
    __table_args__ = (
        UniqueConstraint(
            "learner_id",
            "node_id",
            name="uq_learner_knowledge_states_learner_node",
        ),
        Index("ix_learner_knowledge_states_learner", "learner_id"),
        Index("ix_learner_knowledge_states_node", "node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learners.id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id"), nullable=False
    )

    mastery: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    uncertainty: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    conceptual: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    procedural: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    implementation: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    transfer: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    fluency: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    self_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    reasoning: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_assessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_decay_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
