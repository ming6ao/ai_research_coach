"""MisconceptionService (Stage 6).

Misconceptions are learner-specific hypotheses — they are never created
automatically for an incorrect answer; they require explicit diagnostic
evidence (a call to ``suspect_misconception`` or diagnostic evidence routing).
"""

from __future__ import annotations

import uuid
from typing import Optional

from ..domain.errors import (
    LearnerNotFoundError,
    MisconceptionNotFoundError,
    NodeNotFoundError,
    NotMisconceptionNodeError,
)
from ..domain.interfaces import (
    EvidenceRepository,
    KnowledgeGraphRepository,
    LearnerModelRepository,
    MisconceptionRepository,
)
from ..domain.knowledge import utcnow
from ..domain.misconception import (
    DEFAULT_MISCONCEPTION_CONFIG,
    EvidenceRelationship,
    LearnerMisconception,
    MisconceptionConfig,
    MisconceptionEvidenceLink,
    MisconceptionStatus,
)
from ..domain.types import NodeType


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
            from ..domain.errors import EvidenceNotFoundError

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

        self._misconceptions.add_evidence_link(
            MisconceptionEvidenceLink(
                misconception_id=mc.id,
                evidence_id=evidence_id,
                relationship=relationship,
            )
        )

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

        updated = mc.model_copy(
            update={
                "confidence": round(min(1.0, max(0.0, confidence)), 4),
                "status": status,
                "last_observed_at": now,
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