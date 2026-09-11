"""Learning frontier: readiness computation, policy input, and SQL persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, Field
from learner.graph import utcnow, KnowledgeNode
from learner.interfaces import (
    AssessmentTargetRepository,
    AssessmentTaskRepository,
    FrontierRepository,
    KnowledgeGraphRepository,
    LearnerModelRepository,
)
from learner.states import StateStatus
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


class FrontierStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    DEFERRED = "deferred"
    COMPLETED = "completed"


class FrontierConfig(BaseModel):
    """Deterministic priority weights (Section 3 — all configurable)."""

    model_config = ConfigDict(extra="forbid")

    # relevance per generation source.
    relevance_prerequisite: float = 1.0
    relevance_related: float = 0.9
    relevance_uncertainty: float = 0.8
    relevance_low_mastery: float = 0.8
    relevance_task_required: float = 0.9
    relevance_adjacent: float = 0.7

    importance_default: float = 0.7
    prerequisite_factor: float = 1.0
    non_prerequisite_factor: float = 0.9

    # Filtering (Section 4): skip highly mastered, low-uncertainty nodes unless
    # the reason is task-required or an explicit learner request.
    skip_mastered: bool = True
    mastered_uncertainty_max: float = 0.25
    low_mastery_threshold: float = 0.5


DEFAULT_FRONTIER_CONFIG = FrontierConfig()

# Reasons that override the mastered/low-uncertainty filter.
_FILTER_EXEMPT_REASONS = {"task_required", "explicit_request"}


class LearnerFrontier(BaseModel):
    """One frontier entry for a learner on a node."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    learner_id: uuid.UUID
    node_id: uuid.UUID
    priority: float = Field(ge=0.0, le=1.0)
    reason: str
    source_node_id: Optional[uuid.UUID] = None
    status: FrontierStatus = FrontierStatus.CANDIDATE
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)



class FrontierService:
    def __init__(
        self,
        frontier_repository: FrontierRepository,
        learner_repository: LearnerModelRepository,
        knowledge_repository: KnowledgeGraphRepository,
        task_repository: Optional[AssessmentTaskRepository] = None,
        target_repository: Optional[AssessmentTargetRepository] = None,
        config: Optional[FrontierConfig] = None,
    ) -> None:
        self._frontier = frontier_repository
        self._learners = learner_repository
        self._knowledge = knowledge_repository
        self._tasks = task_repository
        self._targets = target_repository
        self.config = config or DEFAULT_FRONTIER_CONFIG

    # -- generation ------------------------------------------------------------

    def generate(
        self,
        learner_id: uuid.UUID,
        topic_node_id: Optional[uuid.UUID] = None,
        *,
        explicit_request: Optional[set[uuid.UUID]] = None,
    ) -> list[LearnerFrontier]:
        """Regenerate the frontier for a learner and persist it (idempotent upsert)."""
        topic = self._knowledge.get_node(topic_node_id) if topic_node_id else None
        states = {s.node_id: s for s in self._learners.list_learner_states(learner_id)}

        candidates: dict[uuid.UUID, tuple[float, str, Optional[uuid.UUID]]] = {}

        prereq_ids: set[uuid.UUID] = set()
        if topic is not None:
            prereq_ids = {n.id for n in self._direct_prerequisites(topic.id)}
            for nid in prereq_ids:
                self._add(candidates, nid, self.config.relevance_prerequisite, "prerequisite", topic.id, states)
            for nid in self._related_ids(topic.id):
                if nid != topic.id:
                    self._add(candidates, nid, self.config.relevance_related, "related", topic.id, states)

        for nid, state in states.items():
            if state.is_uncertain():
                self._add(candidates, nid, self.config.relevance_uncertainty, "uncertain", None, states)
            if state.is_low_mastery():
                self._add(candidates, nid, self.config.relevance_low_mastery, "low_mastery", None, states)

        for nid in self._task_target_ids():
            self._add(candidates, nid, self.config.relevance_task_required, "task_required", topic.id if topic else None, states)

        if explicit_request:
            for nid in explicit_request:
                self._add(candidates, nid, 1.0, "explicit_request", topic.id if topic else None, states)

        if topic is not None:
            for nid in self._adjacent_ids(prereq_ids, states):
                self._add(candidates, nid, self.config.relevance_adjacent, "adjacent", topic.id, states)

        entries: list[LearnerFrontier] = []
        for nid in sorted(candidates, key=lambda x: str(x)):
            priority, reason, source = candidates[nid]
            entry = self._build_entry(learner_id, nid, priority, reason, source, states)
            if entry.priority <= 0:
                continue  # filtered: mastered + low-uncertainty, not exempt
            self._frontier.upsert(entry)
            entries.append(self._frontier.get(learner_id, nid))
        entries.sort(key=lambda e: (-e.priority, str(e.node_id)))
        return entries

    def _add(
        self,
        candidates: dict,
        node_id: uuid.UUID,
        relevance: float,
        reason: str,
        source: Optional[uuid.UUID],
        states: dict,
    ) -> None:
        existing = candidates.get(node_id)
        if existing is None:
            candidates[node_id] = (relevance, reason, source)
            return
        cur_relevance, cur_reason, _ = existing
        # Filter-exempt reasons (task-required / explicit request) win regardless
        # of relevance so a mastered node required by a task is not dropped.
        if reason in _FILTER_EXEMPT_REASONS and cur_reason not in _FILTER_EXEMPT_REASONS:
            candidates[node_id] = (relevance, reason, source)
        elif cur_reason in _FILTER_EXEMPT_REASONS:
            return
        elif relevance > cur_relevance:
            candidates[node_id] = (relevance, reason, source)

    def _build_entry(
        self,
        learner_id: uuid.UUID,
        node_id: uuid.UUID,
        relevance: float,
        reason: str,
        source: Optional[uuid.UUID],
        states: dict,
    ) -> LearnerFrontier:
        state = states.get(node_id)
        node = self._knowledge.get_node(node_id)
        uncertainty = state.uncertainty if state else 1.0
        importance = float(node.metadata.get("importance", self.config.importance_default)) if node else self.config.importance_default
        prerequisite_factor = (
            self.config.prerequisite_factor
            if source and self._is_prerequisite(node_id, source)
            else self.config.non_prerequisite_factor
        )
        priority = min(1.0, relevance * uncertainty * importance * prerequisite_factor)

        # Filtering (Section 4): mastered + low-uncertainty nodes are skipped
        # unless required for a task or explicitly requested.
        if (
            self.config.skip_mastered
            and state is not None
            and state.status in (StateStatus.PROFICIENT, StateStatus.MASTERED)
            and state.uncertainty <= self.config.mastered_uncertainty_max
            and reason not in ("task_required", "explicit_request")
        ):
            priority = 0.0

        now = utcnow()
        return LearnerFrontier(
            learner_id=learner_id,
            node_id=node_id,
            priority=round(priority, 4),
            reason=reason,
            source_node_id=source,
            status=FrontierStatus.CANDIDATE,
            created_at=now,
            updated_at=now,
        )

    # -- status helpers ---------------------------------------------------------

    def set_status(
        self, learner_id: uuid.UUID, node_id: uuid.UUID, status: FrontierStatus
    ) -> Optional[LearnerFrontier]:
        entry = self._frontier.get(learner_id, node_id)
        if entry is None:
            return None
        updated = entry.model_copy(update={"status": status, "updated_at": utcnow()})
        return self._frontier.upsert(updated)

    def list_frontier(
        self, learner_id: uuid.UUID, status: Optional[FrontierStatus] = None
    ) -> list[LearnerFrontier]:
        entries = self._frontier.list_for_learner(learner_id)
        if status is not None:
            entries = [e for e in entries if e.status == status]
        return entries

    # -- graph helpers -------------------------------------------------------------

    def _direct_prerequisites(self, node_id: uuid.UUID) -> list[KnowledgeNode]:
        from learner.traversal import direct_prerequisites

        return direct_prerequisites(self._knowledge, node_id)

    def _related_ids(self, node_id: uuid.UUID) -> set[uuid.UUID]:
        return {n.id for n in self._knowledge.get_related_nodes(node_id)}

    def _is_prerequisite(self, node_id: uuid.UUID, source_id: uuid.UUID) -> bool:
        if source_id is None:
            return False
        return node_id in {n.id for n in self._direct_prerequisites(source_id)}

    def _task_target_ids(self) -> set[uuid.UUID]:
        if self._tasks is None or self._targets is None:
            return set()
        ids: set[uuid.UUID] = set()
        for task in self._tasks.list_tasks():
            ids.update(t.node_id for t in self._targets.list_targets_for_task(task.id))
        return ids

    def _adjacent_ids(self, prereq_ids: set[uuid.UUID], states: dict) -> set[uuid.UUID]:
        adjacent: set[uuid.UUID] = set()
        for pid in prereq_ids:
            adjacent.update(self._related_ids(pid))
        return {nid for nid in adjacent if nid in states and nid not in prereq_ids}

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
        now = utcnow()
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
