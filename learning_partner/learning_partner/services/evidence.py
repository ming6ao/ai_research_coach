"""EvidenceService: application-level orchestration for learner evidence.

Responsibilities:

- Enforce that evidence is append-only (only ``add_evidence`` writes; no update/delete).
- Validate that the learner and node referenced by evidence actually exist.
- Aggregate evidence into a summary WITHOUT changing any learner-model estimate
  (that is a later stage).
"""

from __future__ import annotations

import uuid
from typing import Optional

from ..domain.errors import LearnerNotFoundError, NodeNotFoundError
from ..domain.evidence import (
    Evidence,
    EvidenceFilter,
    EvidenceSummary,
    ObservationStatus,
)
from ..domain.interfaces import (
    EvidenceRepository,
    KnowledgeGraphRepository,
    LearnerModelRepository,
)


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

    def list_evidence_for_interaction(
        self, interaction_id: uuid.UUID, filters: Optional[EvidenceFilter] = None
    ) -> list[Evidence]:
        return self.evidence_repository.list_evidence_for_interaction(interaction_id, filters)

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