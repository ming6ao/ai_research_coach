"""Domain models for assessment tasks and assessment targets.

Answers the question: *"What task can provide evidence about which
competencies?"*

- ``AssessmentTask`` — an instrument that can be given to a learner.
- ``AssessmentTarget`` — a link from a task to a knowledge node, describing the
  role that node plays in the task and how strongly the task is expected to
  reveal the learner's ability on it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .knowledge import utcnow


class TaskType(str, Enum):
    """The kind of activity an assessment task asks the learner to perform."""

    CODING = "coding"
    EXPLANATION = "explanation"
    DEBUGGING = "debugging"
    PREDICTION = "prediction"
    DESIGN = "design"
    MULTIPLE_CHOICE = "multiple_choice"
    TRACE = "trace"
    TEACH_BACK = "teach_back"


class TargetRole(str, Enum):
    """What role a knowledge node plays in an assessment task."""

    PRIMARY = "primary"          # the task directly measures this node
    SECONDARY = "secondary"      # exercised by the task, measured incidentally
    PREREQUISITE = "prerequisite"  # must be known for the task to be attempted
    DIAGNOSTIC = "diagnostic"    # probed to separate competing misconceptions


class AssessmentTask(BaseModel):
    """An assessment instrument given to a learner."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    task_type: TaskType
    title: str
    prompt: str
    difficulty: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AssessmentTarget(BaseModel):
    """Link from an assessment task to a knowledge node it exercises.

    ``(task_id, node_id)`` must be unique within a task. ``expected_signal_strength``
    is in [0, 1]: how strongly the task's outcome is expected to reveal the
    learner's ability on this node.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    task_id: uuid.UUID
    node_id: uuid.UUID
    target_role: TargetRole
    expected_signal_strength: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)