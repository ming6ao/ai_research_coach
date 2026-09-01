"""Deterministic learner-state updates from evidence (Stage 5).

No Bayesian inference, IRT, ML, or LLM. The engine is a transparent,
confidence-weighted moving update that can be inspected and tested:

- ``base_performance`` is read from ``observation_status``.
- ``effective_weight = expected_signal_strength * evidence_quality``.
- ``evidence_quality`` averages ONLY the observed quality dimensions
  (confidence, reasoning quality, independence); unobserved dimensions are
  never inferred.
- Mastery moves a configurable fraction of the way toward observed performance
  (so a single observation never jumps mastery to 0 or 1).
- Uncertainty shrinks multiplicatively as applied evidence accumulates.
- ``ambiguous`` and ``not_observed`` evidence is ignored for mastery updates.
- ``self_report`` evidence moves only ``self_confidence`` (subjective, not
  performance). ``conversation`` evidence is low-strength supporting evidence.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .evidence import Evidence, EvidenceType, ObservationStatus
from .knowledge import utcnow
from .learner import (
    LearnerKnowledgeState,
    StateStatus,
    UNKNOWN_MASTERY,
    UNKNOWN_UNCERTAINTY,
)


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


class StateUpdateRecord(BaseModel):
    """Audit row for learner_state_updates (Section 6)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    learner_id: uuid.UUID
    node_id: uuid.UUID
    evidence_id: uuid.UUID
    previous_mastery: float
    new_mastery: float
    previous_uncertainty: float
    new_uncertainty: float
    update_reason: str
    created_at: datetime = Field(default_factory=utcnow)


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

    def to_audit_record(self, update: LearnerUpdate) -> StateUpdateRecord:
        return StateUpdateRecord(
            learner_id=update.learner_id,
            node_id=update.node_id,
            evidence_id=update.evidence_id,
            previous_mastery=update.previous_state.mastery,
            new_mastery=update.new_state.mastery,
            previous_uncertainty=update.previous_state.uncertainty,
            new_uncertainty=update.new_state.uncertainty,
            update_reason=update.update_reason,
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