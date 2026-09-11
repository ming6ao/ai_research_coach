"""State updates: Bayesian mastery/uncertainty engine and the update service."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from learner.evidence import Evidence, EvidenceType, ObservationStatus
from learner.graph import utcnow
from learner.states import (
    LearnerKnowledgeState,
    StateStatus,
    UNKNOWN_MASTERY,
    UNKNOWN_UNCERTAINTY,
    UNKNOWN_DIMENSION,
)
from learner.types import LearnerNotFoundError, NodeNotFoundError
from learner.interfaces import KnowledgeGraphRepository, LearnerModelRepository


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class UpdateConfig(BaseModel):
    """Configurable parameters for the update engine (Stage 5, section 5)."""

    model_config = ConfigDict(extra="forbid")

    # moving-update rate; caps how far one observation can move mastery.
    learning_rate: float = 0.4
    # multiplicative uncertainty reduction applied per weighted observation.
    uncertainty_reduction: float = 0.5

    # evidence-quality weights (averaged over OBSERVED dimensions only).
    confidence_weight: float = 0.5
    reasoning_weight: float = 0.3
    independence_weight: float = 0.2

    # low-strength supporting evidence multiplier for conversation evidence.
    conversation_strength: float = 0.3

    # status thresholds (see LearnerKnowledgeState.derive_status).
    uncertain_uncertainty: float = 0.35
    developing_mastery: float = 0.70
    proficient_mastery: float = 0.70
    proficient_uncertainty: float = 0.25
    mastered_mastery: float = 0.85
    mastered_uncertainty: float = 0.15


DEFAULT_UPDATE_CONFIG = UpdateConfig()

# Base performance by observation status (Section 2).
_BASE_PERFORMANCE = {
    ObservationStatus.CORRECT: 1.0,
    ObservationStatus.INCORRECT: 0.0,
    ObservationStatus.PARTIALLY_CORRECT: 0.5,
}
# Statuses that are ignored for mastery updates (Section 2).
_IGNORED_STATUSES = (ObservationStatus.AMBIGUOUS, ObservationStatus.NOT_OBSERVED)

# Competency dimension mapping by evidence type (Section 4).
# "debugging" maps reasoning to the ``reasoning`` competency dimension.
DIMENSION_MAP: dict[EvidenceType, tuple[str, ...]] = {
    EvidenceType.EXPLANATION: ("conceptual",),
    EvidenceType.CODE: ("implementation", "procedural"),
    EvidenceType.PREDICTION: ("conceptual", "transfer"),
    EvidenceType.DEBUGGING: ("implementation", "reasoning"),
    EvidenceType.TEACH_BACK: ("conceptual", "transfer"),
    EvidenceType.SELF_REPORT: ("self_confidence",),
    EvidenceType.TRACE: ("procedural",),
    EvidenceType.ANSWER: (),
    EvidenceType.CONVERSATION: (),
}


class LearnerUpdate(BaseModel):
    """The result of applying one evidence record to a state."""

    model_config = ConfigDict(extra="forbid")

    learner_id: uuid.UUID
    node_id: uuid.UUID
    evidence_id: uuid.UUID
    previous_state: LearnerKnowledgeState
    new_state: LearnerKnowledgeState
    base_performance: float
    effective_weight: float
    update_reason: str


class UpdateEngine:
    """Pure, deterministic application of one evidence record to one state."""

    def __init__(self, config: Optional[UpdateConfig] = None) -> None:
        self.config = config or DEFAULT_UPDATE_CONFIG

    # -- public -----------------------------------------------------------

    def apply(
        self,
        previous: LearnerKnowledgeState,
        evidence: Evidence,
        expected_signal_strength: float = 1.0,
    ) -> Optional[LearnerUpdate]:
        """Apply ``evidence`` to ``previous``; returns None when evidence is ignored."""
        if evidence.observation_status in _IGNORED_STATUSES:
            return None

        base = _BASE_PERFORMANCE[evidence.observation_status]
        quality = self._evidence_quality(evidence)
        weight = clamp01(expected_signal_strength) * quality
        if evidence.evidence_type == EvidenceType.CONVERSATION:
            weight *= self.config.conversation_strength
        if weight <= 0.0:
            return None

        reason = (
            f"{evidence.observation_status.value} {evidence.evidence_type.value} "
            f"evidence (weight={weight:.3f})"
        )

        # self_report moves only self_confidence. The target is the learner's
        # reported confidence (the observed dimension); correctness is not
        # performance evidence for a self-report.
        if evidence.evidence_type == EvidenceType.SELF_REPORT:
            target = evidence.confidence if evidence.confidence is not None else base
            moved = self._move_dimension(previous, ("self_confidence",), target, weight)
            new = moved.model_copy(
                update={
                    "evidence_count": previous.evidence_count + 1,
                    "last_assessed_at": evidence.created_at,
                    "status": LearnerKnowledgeState.derive_status(
                        previous.evidence_count + 1,
                        previous.mastery,
                        previous.uncertainty,
                        self.config,
                    ),
                    "updated_at": evidence.created_at,
                }
            )
            return LearnerUpdate(
                learner_id=previous.learner_id,
                node_id=previous.node_id,
                evidence_id=evidence.id,
                previous_state=previous,
                new_state=new,
                base_performance=base,
                effective_weight=weight,
                update_reason=reason,
            )

        mastery = self._move(previous.mastery, base, weight)
        uncertainty = clamp01(
            previous.uncertainty * (1.0 - self.config.uncertainty_reduction * weight)
        )
        dims = DIMENSION_MAP.get(evidence.evidence_type, ())
        state = previous.model_copy(
            update={
                "mastery": mastery,
                "uncertainty": uncertainty,
                **self._dimension_deltas(previous, dims, base, weight),
                "evidence_count": previous.evidence_count + 1,
                "last_assessed_at": evidence.created_at,
                "status": LearnerKnowledgeState.derive_status(
                    previous.evidence_count + 1, mastery, uncertainty, self.config
                ),
                "updated_at": evidence.created_at,
            }
        )
        return LearnerUpdate(
            learner_id=previous.learner_id,
            node_id=previous.node_id,
            evidence_id=evidence.id,
            previous_state=previous,
            new_state=state,
            base_performance=base,
            effective_weight=weight,
            update_reason=reason,
        )

    # -- helpers -----------------------------------------------------------

    def _evidence_quality(self, evidence: Evidence) -> float:
        """Average ONLY observed quality dimensions. Unobserved = not inferred."""
        parts: list[tuple[float, float]] = []
        if evidence.confidence is not None:
            parts.append((evidence.confidence, self.config.confidence_weight))
        if evidence.reasoning_quality is not None:
            parts.append((evidence.reasoning_quality, self.config.reasoning_weight))
        if evidence.independence is not None:
            parts.append((evidence.independence, self.config.independence_weight))
        if not parts:
            return 1.0
        num = sum(v * w for v, w in parts)
        den = sum(w for _, w in parts)
        return num / den

    def _move(self, current: float, target: float, weight: float) -> float:
        return clamp01(current + self.config.learning_rate * weight * (target - current))

    def _dimension_deltas(
        self, state: LearnerKnowledgeState, dims: tuple[str, ...], target: float, weight: float
    ) -> dict[str, float]:
        return {d: self._move(getattr(state, d), target, weight) for d in dims}

    def _move_dimension(
        self, state: LearnerKnowledgeState, dims: tuple[str, ...], target: float, weight: float
    ) -> LearnerKnowledgeState:
        return state.model_copy(update=self._dimension_deltas(state, dims, target, weight))

class LearnerUpdateService:
    """Apply an immutable evidence record to the learner state."""

    def __init__(
        self,
        learner_repository: LearnerModelRepository,
        knowledge_repository: KnowledgeGraphRepository,
        config: Optional[UpdateConfig] = None,
    ) -> None:
        self._learners = learner_repository
        self._knowledge = knowledge_repository
        self._engine = UpdateEngine(config or DEFAULT_UPDATE_CONFIG)

    @property
    def engine(self) -> UpdateEngine:
        return self._engine

    def apply_evidence(
        self,
        evidence,
        expected_signal_strength: float = 1.0,
    ) -> Optional[LearnerUpdate]:
        """Persist the state change caused by ``evidence`` (if any).

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
