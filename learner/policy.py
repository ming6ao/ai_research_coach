"""Policy: candidate actions and next-action selection over the frontier."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from learner.frontier import LearnerFrontier
from learner.interfaces import (
    KnowledgeGraphRepository,
    LearnerModelRepository,
    MisconceptionRepository,
)
from learner.states import LearnerKnowledgeState, StateStatus
from learner.misconception import LearnerMisconception


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

class PolicyEngine:
    def __init__(
        self,
        learner_repository: LearnerModelRepository,
        knowledge_repository: KnowledgeGraphRepository,
        misconception_repository: MisconceptionRepository,
        config: Optional[PolicyConfig] = None,
    ) -> None:
        self._learners = learner_repository
        self._knowledge = knowledge_repository
        self._misconceptions = misconception_repository
        self.config = config or DEFAULT_POLICY_CONFIG

    def generate(
        self,
        learner_id: uuid.UUID,
        frontier: list[LearnerFrontier],
    ) -> list[CandidateAction]:
        states = {s.node_id: s for s in self._learners.list_learner_states(learner_id)}
        misconceptions = self._misconceptions.list_for_learner(learner_id)
        active_mc_by_node = {
            mc.misconception_node_id: mc for mc in misconceptions if mc.is_active
        }

        actions: list[CandidateAction] = []
        for entry in frontier:
            if entry.priority <= 0:
                continue
            action = self._score_node(
                learner_id, entry, states.get(entry.node_id), active_mc_by_node
            )
            if action is not None:
                actions.append(action)

        for node_id, mc in active_mc_by_node.items():
            actions.append(self._misconception_action(learner_id, node_id, mc))

        actions.sort(key=lambda a: (-a.total_score, str(a.target_node_id)))
        return actions

    # -- per-node scoring ------------------------------------------------------

    def _score_node(
        self,
        learner_id: uuid.UUID,
        entry: LearnerFrontier,
        state: Optional[LearnerKnowledgeState],
        active_mc_by_node: dict,
    ) -> Optional[CandidateAction]:
        node = self._knowledge.get_node(entry.node_id)
        if node is None:
            return None
        state = state or self._neutral(entry.node_id)
        importance = float(node.metadata.get("importance", self.config.importance_default))

        action_type = self._choose_action_type(state, entry.node_id in active_mc_by_node)

        information_gain = state.uncertainty
        learning_value = (1.0 - state.mastery) * importance
        goal_relevance = entry.priority
        difficulty_fit, target_task_id = self._difficulty_fit(entry.node_id, state.mastery)
        frustration_cost = max(0.0, (0.5 - state.mastery) * 0.5)
        redundancy_cost = state.mastery * (1.0 - state.uncertainty)

        total = (
            information_gain
            + learning_value
            + goal_relevance
            + difficulty_fit
            - frustration_cost
            - redundancy_cost
        )

        rationale = (
            f"{action_type.value} on {node.slug} (mastery={state.mastery:.2f}, "
            f"uncertainty={state.uncertainty:.2f}, frontier={entry.priority:.2f})"
        )
        return CandidateAction(
            action_type=action_type,
            target_node_id=entry.node_id,
            target_task_id=target_task_id,
            information_gain=round(information_gain, 4),
            learning_value=round(learning_value, 4),
            goal_relevance=round(goal_relevance, 4),
            difficulty_fit=round(difficulty_fit, 4),
            frustration_cost=round(frustration_cost, 4),
            redundancy_cost=round(redundancy_cost, 4),
            total_score=round(total, 4),
            rationale=rationale,
        )

    def _choose_action_type(
        self, state: LearnerKnowledgeState, has_misconception: bool
    ) -> ActionType:
        if has_misconception:
            return ActionType.MISCONCEPTION_PROBE
        if state.mastery >= self.config.move_on_mastery and state.uncertainty <= self.config.move_on_uncertainty:
            return ActionType.RECAP
        if state.mastery >= self.config.move_on_mastery and state.uncertainty > self.config.probe_uncertainty:
            return ActionType.PROBE
        if state.mastery >= self.config.teach_mastery:
            return ActionType.PROBE
        if state.mastery < self.config.teach_mastery and state.uncertainty > self.config.probe_uncertainty:
            return ActionType.PROBE  # diagnose
        return ActionType.EXPLAIN  # teach / remediate

    def _difficulty_fit(
        self, node_id: uuid.UUID, mastery: float
    ) -> tuple[float, Optional[uuid.UUID]]:
        """Difficulty fit without a persisted task catalog (neutral default)."""
        return 0.6, None

    def _misconception_action(
        self, learner_id: uuid.UUID, node_id: uuid.UUID, mc: LearnerMisconception
    ) -> CandidateAction:
        node = self._knowledge.get_node(node_id)
        # Remediate the underlying skill the misconception applies to, so a
        # follow-up drills a real topic rather than the misconception node itself.
        skill_id = (node.metadata or {}).get("skill_node_id") if node else None
        target_id = uuid.UUID(skill_id) if skill_id else node_id
        target = self._knowledge.get_node(target_id)
        slug = target.slug if target else (node.slug if node else str(node_id))
        return CandidateAction(
            action_type=ActionType.MISCONCEPTION_PROBE,
            target_node_id=target_id,
            target_task_id=None,
            information_gain=1.0,
            learning_value=0.5,
            goal_relevance=0.9,
            difficulty_fit=0.6,
            frustration_cost=0.1,
            redundancy_cost=0.0,
            total_score=round(3.0 + self.config.misconception_boost, 4),
            rationale=f"misconception_probe on {slug} (confidence={mc.confidence:.2f})",
        )

    @staticmethod
    def _neutral(node_id: uuid.UUID) -> LearnerKnowledgeState:
        return LearnerKnowledgeState(
            learner_id=uuid.uuid4(), node_id=node_id,
            mastery=0.5, uncertainty=1.0,
            status=StateStatus.UNKNOWN, evidence_count=0,
        )
