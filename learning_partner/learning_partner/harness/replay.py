"""Replay/evaluation harness (Stage 10).

The harness replays a scripted learner session through the full orchestrator
loop and checks qualitative outcomes — no exact float equality.
"""

from __future__ import annotations

import uuid
from typing import Any

from ..container import build_container
from ..domain.learner import LearnerKnowledgeState, StateStatus
from ..domain.orchestrator import LearnerInteraction
from ..services.assessors import ScriptedEvidenceAssessor
from ..services.orchestrator import LearningOrchestrator
from ..storage.database import Base
from ..seed import (
    seed_misconceptions,
    seed_weighted_sampling,
    seed_weighted_sampling_task,
)
from . import checks
from .models import ReplayReport, StateSnapshot


class ReplayEngine:
    """Replays a scenario dict and reports qualitative results."""

    def __init__(self, session) -> None:
        self._session = session
        Base.metadata.create_all(session.get_bind())

    def run(self, scenario: dict) -> ReplayReport:
        c = build_container(self._session)

        # Seed world.
        seed_weighted_sampling(c.knowledge_repository)
        seed_weighted_sampling_task(c.task_repository, c.target_repository, c.knowledge_repository)
        seed_misconceptions(c.knowledge_repository)

        learner = c.learner_service.create_learner()
        problem = c.knowledge_repository.get_node_by_slug("weighted_sampling_from_scratch")

        # Starting state.
        for slug, values in (scenario.get("starting_states") or {}).items():
            node = c.knowledge_repository.get_node_by_slug(slug)
            if node is None:
                continue
            status = StateStatus(values.get("status", "unknown"))
            state = LearnerKnowledgeState(
                learner_id=learner.id,
                node_id=node.id,
                mastery=values.get("mastery", 0.5),
                uncertainty=values.get("uncertainty", 1.0),
                evidence_count=values.get("evidence_count", 0),
                status=status,
                self_confidence=values.get("self_confidence", 0.5),
            )
            c.learner_service.upsert_state(state)

        # Assessor scripted from scenario interactions.
        script = []
        for interaction in scenario.get("interactions", []):
            script.append(interaction.get("evidence", []))

        def resolver(slug):
            node = c.knowledge_repository.get_node_by_slug(slug)
            return node.id if node else None

        assessor = ScriptedEvidenceAssessor(script, resolver)
        orch = LearningOrchestrator(c, assessor)

        task = c.task_repository.list_tasks()[0] if c.task_repository.list_tasks() else None

        for i, interaction in enumerate(scenario.get("interactions", [])):
            orch.process(
                LearnerInteraction(
                    learner_id=learner.id,
                    session_id=uuid.uuid4(),
                    interaction_id=uuid.uuid4(),
                    topic_node_id=problem.id,
                    assessment_task_id=task.id if task else None,
                    message=interaction["message"],
                )
            )

        report = self._collect(c, learner.id, problem.id, scenario["name"])

        report.passed, report.failures = checks.run_all(scenario.get("assertions", []), report, c, learner.id)
        return report

    @staticmethod
    def _collect(c, learner_id: uuid.UUID, problem_id: uuid.UUID, name: str) -> ReplayReport:
        states: dict[str, StateSnapshot] = {}
        evidence_counts: dict[str, int] = {}
        for s in c.learner_service.list_learner_states(learner_id):
            node = c.knowledge_repository.get_node(s.node_id)
            if node is None:
                continue
            states[node.slug] = StateSnapshot(
                mastery=s.mastery,
                uncertainty=s.uncertainty,
                evidence_count=s.evidence_count,
                status=s.status.value,
                conceptual=s.conceptual,
                procedural=s.procedural,
                implementation=s.implementation,
                transfer=s.transfer,
                fluency=s.fluency,
                self_confidence=s.self_confidence,
                reasoning=s.reasoning,
            )
            summary = c.evidence_service.summarize(learner_id, s.node_id)
            evidence_counts[node.slug] = summary.observation_count

        misconceptions = []
        for mc in c.misconception_service.list_all(learner_id):
            node = c.knowledge_repository.get_node(mc.misconception_node_id)
            misconceptions.append({
                "node": node.slug if node else str(mc.misconception_node_id),
                "status": mc.status.value,
                "confidence": mc.confidence,
            })

        frontier = []
        for f in c.frontier_service.list_frontier(learner_id):
            node = c.knowledge_repository.get_node(f.node_id)
            frontier.append({
                "node": node.slug if node else str(f.node_id),
                "priority": f.priority,
                "reason": f.reason,
                "status": f.status.value,
            })

        actions = []
        frontier_entries = c.frontier_service.list_frontier(learner_id)
        for a in c.policy_engine.generate(learner_id, frontier_entries):
            node = c.knowledge_repository.get_node(a.target_node_id)
            actions.append({
                "action_type": a.action_type.value,
                "node": node.slug if node else str(a.target_node_id),
                "total_score": a.total_score,
            })

        return ReplayReport(
            scenario=name,
            states=states,
            evidence_counts=evidence_counts,
            misconceptions=misconceptions,
            frontier=frontier,
            actions=actions,
            selected_action=actions[0] if actions else None,
        )