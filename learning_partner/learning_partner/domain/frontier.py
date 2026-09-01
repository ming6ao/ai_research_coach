"""Domain models for the learning frontier (Stage 7).

The frontier is the learner-specific set of nodes that are candidates for
future teaching or assessment. It is a derived view: generated from the learner
model + knowledge graph + assessment tasks.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .knowledge import utcnow


class FrontierStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    DEFERRED = "deferred"
    COMPLETED = "completed"


class FrontierConfig(BaseModel):
    """Deterministic priority weights (Section 3 — all configurable)."""

    model_config = ConfigDict(extra="forbid")

    # relevance per generation source.
    relevance_prerequisite: float = 1.0
    relevance_related: float = 0.9
    relevance_uncertainty: float = 0.8
    relevance_low_mastery: float = 0.8
    relevance_task_required: float = 0.9
    relevance_adjacent: float = 0.7

    importance_default: float = 0.7
    prerequisite_factor: float = 1.0
    non_prerequisite_factor: float = 0.9

    # Filtering (Section 4): skip highly mastered, low-uncertainty nodes unless
    # the reason is task-required or an explicit learner request.
    skip_mastered: bool = True
    mastered_uncertainty_max: float = 0.25
    low_mastery_threshold: float = 0.5


DEFAULT_FRONTIER_CONFIG = FrontierConfig()

# Reasons that override the mastered/low-uncertainty filter.
_FILTER_EXEMPT_REASONS = {"task_required", "explicit_request"}


class LearnerFrontier(BaseModel):
    """One frontier entry for a learner on a node."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    learner_id: uuid.UUID
    node_id: uuid.UUID
    priority: float = Field(ge=0.0, le=1.0)
    reason: str
    source_node_id: Optional[uuid.UUID] = None
    status: FrontierStatus = FrontierStatus.CANDIDATE
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)