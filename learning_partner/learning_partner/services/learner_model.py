"""LearnerModelService: application-level orchestration for the learner model.

Responsibilities that belong here (not in the repository, not in SQL):

- Lazy state initialization (a row is created only when a learner encounters
  a node — never eagerly for the whole graph).
- Enforcing the semantic rule that "unknown" is the neutral prior and never
  means "low mastery".
- Deterministic derived semantics (uncertain / low-mastery / mastered lists).
"""

from __future__ import annotations

import uuid
from typing import Optional

from ..domain.errors import LearnerNotFoundError, NodeNotFoundError
from ..domain.interfaces import KnowledgeGraphRepository, LearnerModelRepository
from ..domain.knowledge import utcnow
from ..domain.learner import (
    UNKNOWN_DIMENSION,
    UNKNOWN_MASTERY,
    UNKNOWN_UNCERTAINTY,
    Learner,
    LearnerKnowledgeState,
    StateStatus,
)


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