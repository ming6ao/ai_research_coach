"""Misconceptions: detection, tracking, evidence links, and SQL persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from learner.graph import utcnow
from learner.types import (
    LearnerNotFoundError,
    MisconceptionNotFoundError,
    NodeNotFoundError,
    NotMisconceptionNodeError,
    NodeType,
)
from learner.interfaces import (
    EvidenceRepository,
    KnowledgeGraphRepository,
    LearnerModelRepository,
    MisconceptionRepository,
)
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
from sqlalchemy.orm import Session, Mapped, mapped_column
from coach.db import aware_utc, naive_utc, uid, Base


class MisconceptionStatus(str, Enum):
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"
    RESOLVING = "resolving"
    RESOLVED = "resolved"


class EvidenceRelationship(str, Enum):
    """How an evidence record relates to a misconception hypothesis."""

    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    RESOLVING = "resolving"


class MisconceptionConfig(BaseModel):
    """Deterministic confidence-update parameters."""

    model_config = ConfigDict(extra="forbid")

    suspect_confidence: float = 0.4
    support_step: float = 0.25          # confidence += (1 - c) * step
    contradict_step: float = 0.4        # confidence *= (1 - step)
    confirm_threshold: float = 0.6      # >= => confirmed
    resolve_confidence: float = 0.9     # confidence set when resolved


DEFAULT_MISCONCEPTION_CONFIG = MisconceptionConfig()


class LearnerMisconception(BaseModel):
    """A learner-specific hypothesis that a misconception node is present."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    learner_id: uuid.UUID
    misconception_node_id: uuid.UUID
    confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    status: MisconceptionStatus = MisconceptionStatus.SUSPECTED
    first_detected_at: datetime = Field(default_factory=utcnow)
    last_observed_at: datetime = Field(default_factory=utcnow)
    resolved_at: Optional[datetime] = None
    notes: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _resolved_has_resolved_at(self) -> "LearnerMisconception":
        if self.status == MisconceptionStatus.RESOLVED and self.resolved_at is None:
            raise ValueError("status 'resolved' requires resolved_at")
        return self

    @property
    def is_active(self) -> bool:
        return self.status in (
            MisconceptionStatus.SUSPECTED,
            MisconceptionStatus.CONFIRMED,
            MisconceptionStatus.RESOLVING,
        )


class MisconceptionEvidenceLink(BaseModel):
    """Join between a misconception and the evidence about it."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    misconception_id: uuid.UUID
    evidence_id: uuid.UUID
    relationship: EvidenceRelationship
    created_at: datetime = Field(default_factory=utcnow)

class MisconceptionService:
    def __init__(
        self,
        misconception_repository: MisconceptionRepository,
        learner_repository: LearnerModelRepository,
        knowledge_repository: KnowledgeGraphRepository,
        evidence_repository: Optional[EvidenceRepository] = None,
        config: Optional[MisconceptionConfig] = None,
    ) -> None:
        self._misconceptions = misconception_repository
        self._learners = learner_repository
        self._knowledge = knowledge_repository
        self._evidence = evidence_repository
        self.config = config or DEFAULT_MISCONCEPTION_CONFIG

    def _require_learner(self, learner_id: uuid.UUID) -> None:
        if self._learners.get_learner(learner_id) is None:
            raise LearnerNotFoundError(learner_id)

    def _require_misconception_node(self, node_id: uuid.UUID) -> None:
        node = self._knowledge.get_node(node_id)
        if node is None:
            raise NodeNotFoundError(node_id)
        if node.type != NodeType.MISCONCEPTION:
            raise NotMisconceptionNodeError(node_id)

    def _require_evidence(self, evidence_id: uuid.UUID) -> None:
        if self._evidence is not None and self._evidence.get_evidence(evidence_id) is None:
            from learner.types import EvidenceNotFoundError

            raise EvidenceNotFoundError(evidence_id)

    # -- lifecycle ---------------------------------------------------------

    def suspect_misconception(
        self,
        learner_id: uuid.UUID,
        misconception_node_id: uuid.UUID,
        notes: Optional[str] = None,
    ) -> LearnerMisconception:
        """Open a 'suspected' misconception hypothesis. Idempotent per (learner, node)."""
        self._require_learner(learner_id)
        self._require_misconception_node(misconception_node_id)

        existing = self._find_active(learner_id, misconception_node_id)
        if existing is not None:
            return existing

        now = utcnow()
        mc = LearnerMisconception(
            learner_id=learner_id,
            misconception_node_id=misconception_node_id,
            confidence=self.config.suspect_confidence,
            status=MisconceptionStatus.SUSPECTED,
            first_detected_at=now,
            last_observed_at=now,
            notes=notes,
        )
        return self._misconceptions.save(mc)

    def _find_active(
        self, learner_id: uuid.UUID, node_id: uuid.UUID
    ) -> Optional[LearnerMisconception]:
        for mc in self._misconceptions.list_for_learner(learner_id):
            if mc.misconception_node_id == node_id and mc.is_active:
                return mc
        return None

    # -- evidence linking ----------------------------------------------------

    def add_supporting_evidence(
        self, misconception_id: uuid.UUID, evidence_id: uuid.UUID
    ) -> LearnerMisconception:
        return self._add_evidence(misconception_id, evidence_id, EvidenceRelationship.SUPPORTING)

    def add_contradicting_evidence(
        self, misconception_id: uuid.UUID, evidence_id: uuid.UUID
    ) -> LearnerMisconception:
        return self._add_evidence(misconception_id, evidence_id, EvidenceRelationship.CONTRADICTING)

    def add_resolving_evidence(
        self, misconception_id: uuid.UUID, evidence_id: uuid.UUID
    ) -> LearnerMisconception:
        return self._add_evidence(misconception_id, evidence_id, EvidenceRelationship.RESOLVING)

    def _add_evidence(
        self,
        misconception_id: uuid.UUID,
        evidence_id: uuid.UUID,
        relationship: EvidenceRelationship,
    ) -> LearnerMisconception:
        mc = self._misconceptions.get(misconception_id)
        if mc is None:
            raise MisconceptionNotFoundError(misconception_id)
        self._require_evidence(evidence_id)

        now = utcnow()
        confidence = mc.confidence
        if relationship == EvidenceRelationship.SUPPORTING:
            confidence += (1.0 - mc.confidence) * self.config.support_step
            status = (
                MisconceptionStatus.CONFIRMED
                if confidence >= self.config.confirm_threshold
                else mc.status
            )
        else:  # contradicting / resolving evidence weakens the hypothesis.
            confidence *= (1.0 - self.config.contradict_step)
            status = mc.status
            if relationship == EvidenceRelationship.RESOLVING:
                status = MisconceptionStatus.RESOLVING

        # Evidence links are stored as a JSON list on the misconception's
        # metadata (the dedicated join table was dropped in the merge).
        meta = dict(mc.metadata or {})
        links = list(meta.get("evidence_links") or [])
        links.append({
            "evidence_id": str(evidence_id),
            "relationship": relationship.value,
            "created_at": now.isoformat(),
        })
        meta["evidence_links"] = links

        updated = mc.model_copy(
            update={
                "confidence": round(min(1.0, max(0.0, confidence)), 4),
                "status": status,
                "last_observed_at": now,
                "metadata": meta,
            }
        )
        return self._misconceptions.save(updated)

    # -- resolution -----------------------------------------------------------

    def resolve_misconception(
        self, misconception_id: uuid.UUID
    ) -> LearnerMisconception:
        mc = self._misconceptions.get(misconception_id)
        if mc is None:
            raise MisconceptionNotFoundError(misconception_id)
        updated = mc.model_copy(
            update={
                "status": MisconceptionStatus.RESOLVED,
                "resolved_at": utcnow(),
                "confidence": max(mc.confidence, self.config.resolve_confidence),
            }
        )
        return self._misconceptions.save(updated)

    # -- reads ----------------------------------------------------------------

    def list_active_misconceptions(
        self, learner_id: uuid.UUID
    ) -> list[LearnerMisconception]:
        return [mc for mc in self._misconceptions.list_for_learner(learner_id) if mc.is_active]

    def list_all(self, learner_id: uuid.UUID) -> list[LearnerMisconception]:
        return self._misconceptions.list_for_learner(learner_id)

class SQLLearnerMisconceptionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, misconception: LearnerMisconception) -> LearnerMisconception:
        model = self._session.scalar(
            select(LearnerMisconceptionModel).where(
                LearnerMisconceptionModel.id == uid(misconception.id)
            )
        )
        now = utcnow()
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

class LearnerMisconceptionModel(Base):
    __tablename__ = "learner_misconceptions"
    __table_args__ = (
        Index("ix_misconceptions_learner", "learner_id"),
        Index("ix_misconceptions_node", "misconception_node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learners.id"), nullable=False
    )
    misconception_node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.4)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="suspected")
    first_detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
