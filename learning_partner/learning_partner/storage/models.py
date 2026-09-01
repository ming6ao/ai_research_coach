"""SQLAlchemy ORM models for the knowledge graph.

UUIDs are stored as 36-char strings for portability (works on SQLite and every
other supported dialect without dialect-specific types). Timestamps are stored
naive-UTC and normalized to timezone-aware UTC by the repository layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class KnowledgeNodeModel(Base):
    __tablename__ = "knowledge_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class KnowledgeEdgeModel(Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_node_id",
            "target_node_id",
            "edge_type",
            name="uq_knowledge_edges_source_target_type",
        ),
        Index("ix_knowledge_edges_source", "source_node_id"),
        Index("ix_knowledge_edges_target", "target_node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id"), nullable=False
    )
    target_node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id"), nullable=False
    )
    edge_type: Mapped[str] = mapped_column(String(64), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LearnerModel(Base):
    __tablename__ = "learners"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
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


class EvidenceModel(Base):
    """Immutable, append-only learner evidence. No update/delete operations."""

    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_learner", "learner_id"),
        Index("ix_evidence_node", "node_id"),
        Index("ix_evidence_interaction", "interaction_id"),
        Index("ix_evidence_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learners.id"), nullable=False
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    interaction_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    assessment_task_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
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


class AssessmentTaskModel(Base):
    __tablename__ = "assessment_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AssessmentTargetModel(Base):
    __tablename__ = "assessment_targets"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "node_id",
            name="uq_assessment_targets_task_node",
        ),
        Index("ix_assessment_targets_task", "task_id"),
        Index("ix_assessment_targets_node", "node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_tasks.id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id"), nullable=False
    )
    target_role: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_signal_strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LearnerStateUpdateModel(Base):
    """Audit trail: every state update traceable to the evidence that caused it."""

    __tablename__ = "learner_state_updates"
    __table_args__ = (
        Index("ix_state_updates_learner", "learner_id"),
        Index("ix_state_updates_node", "node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learners.id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id"), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evidence.id"), nullable=False
    )
    previous_mastery: Mapped[float] = mapped_column(Float, nullable=False)
    new_mastery: Mapped[float] = mapped_column(Float, nullable=False)
    previous_uncertainty: Mapped[float] = mapped_column(Float, nullable=False)
    new_uncertainty: Mapped[float] = mapped_column(Float, nullable=False)
    update_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


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


class MisconceptionEvidenceModel(Base):
    __tablename__ = "misconception_evidence"
    __table_args__ = (
        UniqueConstraint(
            "misconception_id",
            "evidence_id",
            name="uq_misconception_evidence_pair",
        ),
        Index("ix_misconception_evidence_mc", "misconception_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    misconception_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learner_misconceptions.id"), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evidence.id"), nullable=False
    )
    relationship: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LearnerFrontierModel(Base):
    __tablename__ = "learner_frontier"
    __table_args__ = (
        UniqueConstraint(
            "learner_id", "node_id", name="uq_learner_frontier_learner_node"
        ),
        Index("ix_learner_frontier_learner", "learner_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learners.id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id"), nullable=False
    )
    priority: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    source_node_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)