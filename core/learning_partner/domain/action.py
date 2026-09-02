"""Domain models for adaptive next-action selection (Stage 8).

Candidates are in-memory/domain objects. Persisting them is optional.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ActionType(str, Enum):
    EXPLAIN = "explain"
    PROBE = "probe"
    CODE = "code"
    DEBUG = "debug"
    CHALLENGE = "challenge"
    RECAP = "recap"
    TRANSFER = "transfer"
    MISCONCEPTION_PROBE = "misconception_probe"


class PolicyConfig(BaseModel):
    """Deterministic heuristic parameters (Section 3)."""

    model_config = ConfigDict(extra="forbid")

    importance_default: float = 0.7
    misconception_boost: float = 0.5
    difficulty_tolerance: float = 0.2

    # behavioral thresholds (Section 4).
    move_on_mastery: float = 0.85
    move_on_uncertainty: float = 0.15
    probe_uncertainty: float = 0.25
    teach_mastery: float = 0.70


DEFAULT_POLICY_CONFIG = PolicyConfig()


class CandidateAction(BaseModel):
    """A scored candidate next interaction."""

    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    target_node_id: uuid.UUID
    target_task_id: Optional[uuid.UUID] = None
    information_gain: float = Field(ge=0.0, le=1.0)
    learning_value: float = Field(ge=0.0, le=1.0)
    goal_relevance: float = Field(ge=0.0, le=1.0)
    difficulty_fit: float = Field(ge=0.0, le=1.0)
    frustration_cost: float = Field(ge=0.0, le=1.0)
    redundancy_cost: float = Field(ge=0.0, le=1.0)
    total_score: float = 0.0
    rationale: str