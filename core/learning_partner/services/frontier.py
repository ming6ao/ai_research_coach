"""FrontierService (Stage 7).

Generates the learner-specific frontier of candidate nodes for future teaching
or assessment, using the knowledge graph, learner states, and assessment tasks.
"""

from __future__ import annotations

import uuid
from typing import Optional

from ..domain.frontier import (
    DEFAULT_FRONTIER_CONFIG,
    FrontierConfig,
    FrontierStatus,
    LearnerFrontier,
)
from ..domain.interfaces import (
    AssessmentTargetRepository,
    AssessmentTaskRepository,
    FrontierRepository,
    KnowledgeGraphRepository,
    LearnerModelRepository,
)
from ..domain.knowledge import KnowledgeNode, utcnow
from ..domain.learner import StateStatus

_FILTER_EXEMPT_REASONS = {"task_required", "explicit_request"}


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
        from .traversal import direct_prerequisites

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