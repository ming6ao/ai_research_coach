"""Repository interfaces (boundary between domain and persistence).

Application code depends on these Protocols; the SQLAlchemy implementation
lives in ``storage``. Keep domain logic out of SQL queries: repositories are
dumb CRUD + relationship lookups. Learner-model semantics (status derivation,
readiness, confidence) live in the domain/service layer, never in SQL.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional, Protocol

from .action import CandidateAction, ActionType
from .assessment import AssessmentTarget, AssessmentTask, TargetRole, TaskType
from .evidence import Evidence, EvidenceFilter
from .frontier import LearnerFrontier
from .knowledge import KnowledgeEdge, KnowledgeNode
from .learner import Learner, LearnerKnowledgeState
from .misconception import LearnerMisconception, MisconceptionEvidenceLink
from .types import EdgeType
from .update import StateUpdateRecord


class KnowledgeGraphRepository(Protocol):
    """Persistence boundary for the knowledge graph."""

    # -- nodes ---------------------------------------------------------
    def create_node(self, node: KnowledgeNode) -> KnowledgeNode: ...
    def get_node(self, node_id: uuid.UUID) -> KnowledgeNode | None: ...
    def get_node_by_slug(self, slug: str) -> KnowledgeNode | None: ...
    def update_node(self, node_id: uuid.UUID, **changes: Any) -> KnowledgeNode: ...
    def delete_node(self, node_id: uuid.UUID, *, force: bool = False) -> bool: ...

    # -- edges ---------------------------------------------------------
    def create_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge: ...
    def get_edge(
        self,
        source_node_id: uuid.UUID,
        target_node_id: uuid.UUID,
        edge_type: EdgeType,
    ) -> KnowledgeEdge | None: ...
    def get_outgoing_edges(self, node_id: uuid.UUID) -> list[KnowledgeEdge]: ...
    def get_incoming_edges(self, node_id: uuid.UUID) -> list[KnowledgeEdge]: ...
    def get_related_nodes(self, node_id: uuid.UUID) -> list[KnowledgeNode]: ...


class LearnerModelRepository(Protocol):
    """Persistence boundary for the learner model.

    Repositories only persist. Lazy initialization, status derivation, and the
    unknown-vs-low-mastery rule live in the service/domain layer.
    """

    def create_learner(self, learner: Learner) -> Learner: ...
    def get_learner(self, learner_id: uuid.UUID) -> Learner | None: ...
    def get_state(
        self, learner_id: uuid.UUID, node_id: uuid.UUID
    ) -> LearnerKnowledgeState | None: ...
    def save_state(self, state: LearnerKnowledgeState) -> LearnerKnowledgeState: ...
    def list_learner_states(self, learner_id: uuid.UUID) -> list[LearnerKnowledgeState]: ...


class EvidenceRepository(Protocol):
    """Append-only persistence boundary for learner evidence.

    Only ``add_evidence`` writes. There is intentionally no update or delete:
    evidence is immutable. Corrections are written as new records.
    """

    def add_evidence(self, evidence: Evidence) -> Evidence: ...
    def get_evidence(self, evidence_id: uuid.UUID) -> Evidence | None: ...
    def list_evidence(
        self, filters: Optional[EvidenceFilter] = None
    ) -> list[Evidence]: ...
    def list_evidence_for_learner(
        self, learner_id: uuid.UUID, filters: Optional[EvidenceFilter] = None
    ) -> list[Evidence]: ...
    def list_evidence_for_node(
        self, node_id: uuid.UUID, filters: Optional[EvidenceFilter] = None
    ) -> list[Evidence]: ...
    def list_evidence_for_interaction(
        self, interaction_id: uuid.UUID, filters: Optional[EvidenceFilter] = None
    ) -> list[Evidence]: ...
    def count_evidence(
        self, filters: Optional[EvidenceFilter] = None
    ) -> int: ...
    def get_latest_evidence(
        self, filters: Optional[EvidenceFilter] = None
    ) -> Evidence | None: ...


class AssessmentTaskRepository(Protocol):
    """Persistence boundary for assessment tasks."""

    def create_task(self, task: AssessmentTask) -> AssessmentTask: ...
    def get_task(self, task_id: uuid.UUID) -> AssessmentTask | None: ...
    def update_task(self, task_id: uuid.UUID, **changes: Any) -> AssessmentTask: ...
    def list_tasks(
        self, task_type: Optional[TaskType] = None
    ) -> list[AssessmentTask]: ...
    def find_tasks_for_node(
        self, node_id: uuid.UUID, role: Optional[TargetRole] = None
    ) -> list[AssessmentTask]: ...


class AssessmentTargetRepository(Protocol):
    """Persistence boundary for task->node targets."""

    def add_target(self, target: AssessmentTarget) -> AssessmentTarget: ...
    def remove_target(self, task_id: uuid.UUID, node_id: uuid.UUID) -> bool: ...
    def list_targets_for_task(
        self, task_id: uuid.UUID, role: Optional[TargetRole] = None
    ) -> list[AssessmentTarget]: ...
    def list_tasks_targeting_node(
        self, node_id: uuid.UUID, role: Optional[TargetRole] = None
    ) -> list[AssessmentTask]: ...


class StateUpdateRepository(Protocol):
    """Persistence for the learner_state_updates audit trail."""

    def add_update(self, record: StateUpdateRecord) -> StateUpdateRecord: ...
    def list_updates(
        self,
        learner_id: Optional[uuid.UUID] = None,
        node_id: Optional[uuid.UUID] = None,
    ) -> list[StateUpdateRecord]: ...


class MisconceptionRepository(Protocol):
    """Persistence for learner misconceptions and their evidence links."""

    def save(self, misconception: LearnerMisconception) -> LearnerMisconception: ...
    def get(self, misconception_id: uuid.UUID) -> LearnerMisconception | None: ...
    def list_for_learner(self, learner_id: uuid.UUID) -> list[LearnerMisconception]: ...
    def add_evidence_link(
        self, link: MisconceptionEvidenceLink
    ) -> MisconceptionEvidenceLink: ...
    def list_evidence_links(
        self, misconception_id: uuid.UUID
    ) -> list[MisconceptionEvidenceLink]: ...


class FrontierRepository(Protocol):
    """Persistence for the learner frontier."""

    def upsert(self, entry: LearnerFrontier) -> LearnerFrontier: ...
    def get(
        self, learner_id: uuid.UUID, node_id: uuid.UUID
    ) -> LearnerFrontier | None: ...
    def list_for_learner(self, learner_id: uuid.UUID) -> list[LearnerFrontier]: ...
    def delete(self, learner_id: uuid.UUID, node_id: uuid.UUID) -> bool: ...