"""Domain models for learner evidence.

Evidence is an **immutable, append-only** record of an observed learner
interaction. It is stored independently of the learner-model estimate so that
history is preserved, auditable, and replayable. Estimates may later be derived
from evidence, but evidence is never changed to match an estimate.

Core semantic rule: **not_observed is not incorrect.** An observation with
status ``not_observed`` must not carry a correctness score, and aggregations
must never count it as incorrect. Missing data is missing data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .knowledge import utcnow


class EvidenceType(str, Enum):
    """What kind of learner interaction produced the observation."""

    ANSWER = "answer"
    EXPLANATION = "explanation"
    CODE = "code"
    DEBUGGING = "debugging"
    PREDICTION = "prediction"
    TRACE = "trace"
    TEACH_BACK = "teach_back"
    SELF_REPORT = "self_report"
    CONVERSATION = "conversation"


class ObservationStatus(str, Enum):
    """How the observation was judged."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIALLY_CORRECT = "partially_correct"
    NOT_OBSERVED = "not_observed"
    AMBIGUOUS = "ambiguous"


class Evidence(BaseModel):
    """An immutable observation of learner performance on a knowledge node.

    ``frozen=True`` makes the model itself read-only after construction; the
    repository is additionally append-only (no update/delete). Corrections are
    recorded as new (superseding) evidence records, never by editing history.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    learner_id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    interaction_id: Optional[uuid.UUID] = None
    assessment_task_id: Optional[uuid.UUID] = None
    node_id: uuid.UUID
    evidence_type: EvidenceType
    observation_status: ObservationStatus
    correctness: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reasoning_quality: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    independence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    observed_behavior: Optional[str] = None
    assessor_explanation: Optional[str] = None
    assessment_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _not_observed_has_no_correctness(self) -> "Evidence":
        """Enforce the core rule: a not-observed record cannot be scored wrong."""
        if (
            self.observation_status == ObservationStatus.NOT_OBSERVED
            and self.correctness is not None
        ):
            raise ValueError("not_observed evidence must not carry a correctness score")
        return self

    # -- status helpers --------------------------------------------------

    def is_correct(self) -> bool:
        return self.observation_status == ObservationStatus.CORRECT

    def is_incorrect(self) -> bool:
        return self.observation_status == ObservationStatus.INCORRECT

    def is_partially_correct(self) -> bool:
        return self.observation_status == ObservationStatus.PARTIALLY_CORRECT

    def is_not_observed(self) -> bool:
        return self.observation_status == ObservationStatus.NOT_OBSERVED

    def is_ambiguous(self) -> bool:
        return self.observation_status == ObservationStatus.AMBIGUOUS


class EvidenceFilter(BaseModel):
    """Query filters for listing/counting evidence."""

    model_config = ConfigDict(extra="forbid")

    learner_id: Optional[uuid.UUID] = None
    node_id: Optional[uuid.UUID] = None
    evidence_type: Optional[EvidenceType] = None
    observation_status: Optional[ObservationStatus] = None
    from_time: Optional[datetime] = None
    to_time: Optional[datetime] = None


class EvidenceSummary(BaseModel):
    """Aggregated evidence summary for a (learner, node) pair.

    ``not_observed`` records are counted separately and never contribute to
    ``incorrect_count`` or to the correctness averages.
    """

    model_config = ConfigDict(extra="forbid")

    learner_id: uuid.UUID
    node_id: uuid.UUID
    observation_count: int
    correct_count: int
    incorrect_count: int
    partial_count: int
    ambiguous_count: int
    not_observed_count: int
    average_correctness: Optional[float] = None
    average_reasoning_quality: Optional[float] = None
    latest_observation: Optional[Evidence] = None
    latest_confidence: Optional[float] = None