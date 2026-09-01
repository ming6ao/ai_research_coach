"""LearningOrchestrator (Stage 9): end-to-end adaptive learning loop.

Sequence:
1. Receive learner interaction.
2. Persist the interaction (as structured evidence; raw transcript kept in memory).
3. Resolve the relevant knowledge nodes.
4. Resolve the current assessment task if applicable.
5. Obtain structured evidence from an EvidenceAssessor interface.
6. Persist immutable evidence.
7. Update learner knowledge state (traceable to evidence).
8. Update misconceptions if diagnostic evidence exists.
9. Expand/update the learning frontier.
10. Generate candidate actions.
11. Select the next action.
12. Return a structured result.

The tutor response itself is never responsible for modifying the learner model:
learner response -> evidence -> learner-model update -> policy -> tutor response.
"""

from __future__ import annotations

import uuid
from typing import Optional

from ..domain.assessment import AssessmentTask, AssessmentTarget
from ..domain.evidence import Evidence
from ..domain.orchestrator import LearnerInteraction, OrchestratorResult
from ..container import Container
from .assessors import EvidenceAssessor


class LearningOrchestrator:
    def __init__(self, container: Container, assessor: EvidenceAssessor) -> None:
        self.container = container
        self.assessor = assessor
        self._transcript: dict[str, list[LearnerInteraction]] = {}

    # -- main entry ------------------------------------------------------------

    def process(self, interaction: LearnerInteraction) -> OrchestratorResult:
        c = self.container

        # 1. Receive interaction; keep a session transcript in memory.
        session_key = str(interaction.session_id) if interaction.session_id else str(interaction.id)
        self._transcript.setdefault(session_key, []).append(interaction)

        # 3. Resolve relevant nodes (topic + prerequisites + related).
        topic = c.knowledge_repository.get_node(interaction.topic_node_id)
        relevant = self._relevant_nodes(interaction.topic_node_id)

        # 4. Resolve current assessment task + its targets.
        task, targets = self._resolve_task(interaction.assessment_task_id)

        # 5. Obtain structured evidence.
        context = {
            "learner_id": interaction.learner_id,
            "session_id": interaction.session_id,
            "interaction_id": interaction.interaction_id or interaction.id,
            "assessment_task_id": interaction.assessment_task_id,
            "interaction_index": len(self._transcript[session_key]) - 1,
        }
        raw_evidence = self.assessor.assess(interaction.message, relevant, task, context)

        # 6. Persist immutable evidence.
        persisted: list[Evidence] = []
        for ev in raw_evidence:
            persisted.append(c.evidence_service.add_evidence(ev))

        # 7. Update learner state per evidence, weighted by target signal.
        updated_states = []
        for ev in persisted:
            signal = self._signal_strength(ev, targets)
            update = c.update_service.apply_evidence(ev, signal)
            if update is not None:
                updated_states.append(update.new_state)

        # 8. Update misconceptions when diagnostic evidence is present.
        self._handle_misconceptions(persisted)

        # 9. Expand/update the frontier.
        frontier = c.frontier_service.generate(
            interaction.learner_id, interaction.topic_node_id
        )

        # 10-11. Generate + select next action.
        actions = c.policy_engine.generate(interaction.learner_id, frontier)
        selected = actions[0] if actions else None

        # 12. Return structured result.
        active_mc = c.misconception_service.list_active_misconceptions(interaction.learner_id)
        rationale = self._rationale(topic, selected, frontier)
        return OrchestratorResult(
            learner_id=interaction.learner_id,
            current_topic=topic,
            updated_states=updated_states,
            new_evidence=persisted,
            active_misconceptions=active_mc,
            frontier=frontier,
            candidate_actions=actions,
            selected_action=selected,
            rationale=rationale,
            current_topic_slug=topic.slug if topic else None,
        )

    # -- helpers -----------------------------------------------------------------

    def _relevant_nodes(self, topic_node_id: uuid.UUID) -> list:
        from .traversal import direct_prerequisites

        c = self.container
        topic = c.knowledge_repository.get_node(topic_node_id)
        if topic is None:
            return []
        nodes = [topic]
        nodes += direct_prerequisites(c.knowledge_repository, topic.id)
        nodes += c.knowledge_repository.get_related_nodes(topic.id)
        seen = set()
        unique = []
        for n in nodes:
            if n.id not in seen:
                seen.add(n.id)
                unique.append(n)
        return unique

    def _resolve_task(
        self, task_id: Optional[uuid.UUID]
    ) -> tuple[Optional[AssessmentTask], list[AssessmentTarget]]:
        c = self.container
        if task_id is None:
            return None, []
        task = c.task_repository.get_task(task_id)
        if task is None:
            return None, []
        targets = c.target_repository.list_targets_for_task(task.id)
        return task, targets

    def _signal_strength(
        self, evidence: Evidence, targets: list[AssessmentTarget]
    ) -> float:
        for t in targets:
            if t.node_id == evidence.node_id:
                return t.expected_signal_strength
        return 1.0

    def _handle_misconceptions(self, evidence: list[Evidence]) -> None:
        c = self.container
        for ev in evidence:
            payload = ev.assessment_payload or {}
            slug = payload.get("misconception_node_slug")
            if not slug:
                continue
            node = c.knowledge_repository.get_node_by_slug(slug)
            if node is None:
                continue
            relationship = payload.get("relationship", "supporting")
            mc = c.misconception_service.suspect_misconception(ev.learner_id, node.id)
            if relationship == "supporting":
                c.misconception_service.add_supporting_evidence(mc.id, ev.id)
            elif relationship == "resolving":
                c.misconception_service.add_contradicting_evidence(mc.id, ev.id)
                c.misconception_service.resolve_misconception(mc.id)
            else:  # contradicting
                c.misconception_service.add_contradicting_evidence(mc.id, ev.id)

    @staticmethod
    def _rationale(topic, selected, frontier) -> str:
        parts = []
        if topic:
            parts.append(f"topic: {topic.slug}")
        if selected:
            parts.append(f"next: {selected.action_type.value} -> {selected.rationale}")
        else:
            parts.append("no action selected")
        if frontier:
            top = [f"{f.node_id}" for f in frontier[:3]]
            parts.append(f"frontier top: {', '.join(top)}")
        return " | ".join(parts)