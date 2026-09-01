"""Domain models for the learner model.

The learner model is deliberately separate from the knowledge graph:

- Knowledge Graph answers: "What exists in the domain?"
- Learner Model answers:  "What do we currently believe this learner can do?"

Semantic rule: **unknown must not mean low mastery.** An unseen node is
represented by a neutral prior (mastery 0.5, maximum uncertainty 1.0, zero
evidence) with status ``unknown`` — never by low scores. A missing row in the
state table and an ``unknown`` state are both "no information", and both are
distinguishable from an assessed low-mastery state.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .knowledge import utcnow

# Neutral prior for an unseen node (see module docstring).
UNKNOWN_MASTERY = 0.5
UNKNOWN_UNCERTAINTY = 1.0
UNKNOWN_DIMENSION = 0.5

# Default status thresholds (configurable via domain.update.UpdateConfig).
UNCERTAINTY_THRESHOLD = 0.35
DEVELOPING_MASTERY = 0.70
PROFICIENT_MASTERY = 0.70
PROFICIENT_UNCERTAINTY = 0.25
MASTERED_MASTERY = 0.85
MASTERED_UNCERTAINTY = 0.15
# Strictly-below-neutral mastery counts as "low". Unknown (0.5) is never low.
LOW_MASTERY_THRESHOLD = UNKNOWN_MASTERY


class StateStatus(str, Enum):
    """Classification of what we believe about a learner on one node."""

    UNKNOWN = "unknown"
    UNCERTAIN = "uncertain"
    DEVELOPING = "developing"
    PROFICIENT = "proficient"
    MASTERED = "mastered"


class Learner(BaseModel):
    """A person being coached."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class LearnerKnowledgeState(BaseModel):
    """What we currently believe about one learner's ability on one knowledge node.

    All scores are in [0, 1]. ``mastery`` is the point-estimate belief;
    ``uncertainty`` is the spread of that belief (1.0 = maximum uncertainty).
    Competency dimensions (conceptual / procedural / implementation / transfer /
    fluency / self_confidence) are sub-scores along the same [0, 1] scale.
    """

    model_config = ConfigDict(extra="forbid")

    learner_id: uuid.UUID
    node_id: uuid.UUID

    mastery: float = Field(default=UNKNOWN_MASTERY, ge=0.0, le=1.0)
    uncertainty: float = Field(default=UNKNOWN_UNCERTAINTY, ge=0.0, le=1.0)

    conceptual: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    procedural: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    implementation: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    transfer: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    fluency: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    self_confidence: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)
    reasoning: float = Field(default=UNKNOWN_DIMENSION, ge=0.0, le=1.0)

    evidence_count: int = Field(default=0, ge=0)
    last_assessed_at: datetime | None = None
    last_decay_at: datetime | None = None

    status: StateStatus = StateStatus.UNKNOWN
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _unknown_means_no_evidence(self) -> "LearnerKnowledgeState":
        """Enforce the core semantic rule: unknown is the neutral prior, not a score."""
        if self.status == StateStatus.UNKNOWN:
            if self.evidence_count != 0:
                raise ValueError("status 'unknown' requires evidence_count == 0")
            if self.mastery != UNKNOWN_MASTERY:
                raise ValueError(f"status 'unknown' requires mastery == {UNKNOWN_MASTERY}")
            if self.uncertainty != UNKNOWN_UNCERTAINTY:
                raise ValueError(f"status 'unknown' requires uncertainty == {UNKNOWN_UNCERTAINTY}")
        return self

    @staticmethod
    def derive_status(
        evidence_count: int, mastery: float, uncertainty: float, config: Any = None
    ) -> StateStatus:
        """Canonical status bucket for a given belief, in [0, 1] scores.

        ``config`` may be any object exposing the threshold attributes
        (e.g. ``domain.update.UpdateConfig``); defaults to the module constants.
        """
        if config is None:
            unc = UNCERTAINTY_THRESHOLD
            dev = DEVELOPING_MASTERY
            prof_m = PROFICIENT_MASTERY
            prof_u = PROFICIENT_UNCERTAINTY
            mast_m = MASTERED_MASTERY
            mast_u = MASTERED_UNCERTAINTY
        else:
            unc = config.uncertain_uncertainty
            dev = config.developing_mastery
            prof_m = config.proficient_mastery
            prof_u = config.proficient_uncertainty
            mast_m = config.mastered_mastery
            mast_u = config.mastered_uncertainty

        if evidence_count == 0:
            return StateStatus.UNKNOWN
        if uncertainty > unc:
            return StateStatus.UNCERTAIN
        if mastery >= mast_m and uncertainty <= mast_u:
            return StateStatus.MASTERED
        if mastery >= prof_m and uncertainty <= prof_u:
            return StateStatus.PROFICIENT
        return StateStatus.DEVELOPING

    # -- deterministic derived helpers -----------------------------------

    def is_unknown(self) -> bool:
        """No evidence has been observed for this node yet."""
        return self.status == StateStatus.UNKNOWN

    def is_uncertain(self) -> bool:
        """Belief is not confident: unknown, or uncertain even with some evidence."""
        return self.status in (StateStatus.UNKNOWN, StateStatus.UNCERTAIN)

    def is_low_mastery(self) -> bool:
        """Mastery is strictly below the neutral prior.

        Never true for an ``unknown`` state (whose mastery is exactly 0.5).
        """
        return self.mastery < LOW_MASTERY_THRESHOLD

    def is_mastered(self) -> bool:
        """Learner is believed to have mastered the node."""
        return self.status == StateStatus.MASTERED

    def is_ready_for_assessment(self) -> bool:
        """We should assess this node: the belief is not yet confident."""
        return self.is_unknown() or self.is_uncertain()

    def confidence_level(self) -> float:
        """Complement of uncertainty, in [0, 1]."""
        return 1.0 - self.uncertainty