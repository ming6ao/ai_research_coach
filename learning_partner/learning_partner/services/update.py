"""LearnerUpdateService: applies evidence to the learner model + audit trail."""

from __future__ import annotations

import uuid
from typing import Optional

from ..domain.errors import LearnerNotFoundError, NodeNotFoundError
from ..domain.interfaces import (
    KnowledgeGraphRepository,
    LearnerModelRepository,
    StateUpdateRepository,
)
from ..domain.knowledge import utcnow
from ..domain.learner import (
    UNKNOWN_DIMENSION,
    UNKNOWN_MASTERY,
    UNKNOWN_UNCERTAINTY,
    LearnerKnowledgeState,
    StateStatus,
)
from ..domain.update import (
    DEFAULT_UPDATE_CONFIG,
    UpdateConfig,
    UpdateEngine,
    LearnerUpdate,
)


class LearnerUpdateService:
    """Apply an immutable evidence record to the learner state and audit it.

    The update math lives in ``domain.update.UpdateEngine`` (pure + testable);
    this service only wires persistence and guarantees references exist.
    """

    def __init__(
        self,
        learner_repository: LearnerModelRepository,
        knowledge_repository: KnowledgeGraphRepository,
        update_repository: StateUpdateRepository,
        config: Optional[UpdateConfig] = None,
    ) -> None:
        self._learners = learner_repository
        self._knowledge = knowledge_repository
        self._updates = update_repository
        self._engine = UpdateEngine(config or DEFAULT_UPDATE_CONFIG)

    @property
    def engine(self) -> UpdateEngine:
        return self._engine

    def apply_evidence(
        self,
        evidence,
        expected_signal_strength: float = 1.0,
    ) -> Optional[LearnerUpdate]:
        """Persist the state change caused by ``evidence`` (if any) + audit row.

        Returns None when the evidence is ignored (ambiguous / not_observed).
        """
        if self._learners.get_learner(evidence.learner_id) is None:
            raise LearnerNotFoundError(evidence.learner_id)
        if self._knowledge.get_node(evidence.node_id) is None:
            raise NodeNotFoundError(evidence.node_id)

        previous = self._learners.get_state(evidence.learner_id, evidence.node_id)
        if previous is None:
            previous = self._initialize(evidence.learner_id, evidence.node_id)

        update = self._engine.apply(previous, evidence, expected_signal_strength)
        if update is None:
            return None

        self._learners.save_state(update.new_state)
        self._updates.add_update(self._engine.to_audit_record(update))
        return update

    def _initialize(self, learner_id: uuid.UUID, node_id: uuid.UUID) -> LearnerKnowledgeState:
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