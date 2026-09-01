"""Domain models for the adaptive learning loop (Stage 9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..domain.action import CandidateAction
from ..domain.evidence import Evidence
from ..domain.frontier import LearnerFrontier
from ..domain.knowledge import KnowledgeNode, utcnow
from ..domain.learner import LearnerKnowledgeState
from ..domain.misconception import LearnerMisconception


class LearnerInteraction(BaseModel):
    """A single learner turn in a session."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    learner_id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    interaction_id: Optional[uuid.UUID] = None
    topic_node_id: uuid.UUID
    assessment_task_id: Optional[uuid.UUID] = None
    message: str
    created_at: datetime = Field(default_factory=utcnow)


class OrchestratorResult(BaseModel):
    """Structured result returned by LearningOrchestrator.process."""

    model_config = ConfigDict(extra="forbid")

    learner_id: uuid.UUID
    current_topic: Optional[KnowledgeNode] = None
    updated_states: list[LearnerKnowledgeState] = Field(default_factory=list)
    new_evidence: list[Evidence] = Field(default_factory=list)
    active_misconceptions: list[LearnerMisconception] = Field(default_factory=list)
    frontier: list[LearnerFrontier] = Field(default_factory=list)
    candidate_actions: list[CandidateAction] = Field(default_factory=list)
    selected_action: Optional[CandidateAction] = None
    rationale: str = ""
    current_topic_slug: Optional[str] = None