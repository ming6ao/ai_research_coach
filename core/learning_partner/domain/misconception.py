"""Domain models for learner misconceptions (Stage 6).

Misconceptions are learner-specific hypotheses about a faulty mental model
represented by a knowledge-graph node of type ``misconception``. They are NOT
created automatically for every incorrect answer — they require explicit
diagnostic evidence.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .knowledge import utcnow


class MisconceptionStatus(str, Enum):
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"
    RESOLVING = "resolving"
    RESOLVED = "resolved"


class EvidenceRelationship(str, Enum):
    """How an evidence record relates to a misconception hypothesis."""

    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    RESOLVING = "resolving"


class MisconceptionConfig(BaseModel):
    """Deterministic confidence-update parameters."""

    model_config = ConfigDict(extra="forbid")

    suspect_confidence: float = 0.4
    support_step: float = 0.25          # confidence += (1 - c) * step
    contradict_step: float = 0.4        # confidence *= (1 - step)
    confirm_threshold: float = 0.6      # >= => confirmed
    resolve_confidence: float = 0.9     # confidence set when resolved


DEFAULT_MISCONCEPTION_CONFIG = MisconceptionConfig()


class LearnerMisconception(BaseModel):
    """A learner-specific hypothesis that a misconception node is present."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    learner_id: uuid.UUID
    misconception_node_id: uuid.UUID
    confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    status: MisconceptionStatus = MisconceptionStatus.SUSPECTED
    first_detected_at: datetime = Field(default_factory=utcnow)
    last_observed_at: datetime = Field(default_factory=utcnow)
    resolved_at: Optional[datetime] = None
    notes: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _resolved_has_resolved_at(self) -> "LearnerMisconception":
        if self.status == MisconceptionStatus.RESOLVED and self.resolved_at is None:
            raise ValueError("status 'resolved' requires resolved_at")
        return self

    @property
    def is_active(self) -> bool:
        return self.status in (
            MisconceptionStatus.SUSPECTED,
            MisconceptionStatus.CONFIRMED,
            MisconceptionStatus.RESOLVING,
        )


class MisconceptionEvidenceLink(BaseModel):
    """Join between a misconception and the evidence about it."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    misconception_id: uuid.UUID
    evidence_id: uuid.UUID
    relationship: EvidenceRelationship
    created_at: datetime = Field(default_factory=utcnow)