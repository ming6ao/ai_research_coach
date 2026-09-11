"""Orchestration: evidence assessors and the assess->update->remediate loop."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Callable, Protocol
from pydantic import BaseModel, ConfigDict, Field
from learner.policy import CandidateAction
from learner.evidence import Evidence, EvidenceType, ObservationStatus
from learner.frontier import LearnerFrontier
from learner.graph import KnowledgeNode, utcnow
from learner.states import LearnerKnowledgeState
from learner.misconception import LearnerMisconception
from learner.container import Container


class LearnerInteraction(BaseModel):
    """A single learner turn in a session."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    learner_id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    interaction_id: Optional[uuid.UUID] = None
    topic_node_id: uuid.UUID
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

        # 5. Obtain structured evidence.
        context = {
            "learner_id": interaction.learner_id,
            "session_id": interaction.session_id,
            "interaction_id": interaction.interaction_id or interaction.id,
            "interaction_index": len(self._transcript[session_key]) - 1,
        }
        raw_evidence = self.assessor.assess(interaction.message, relevant, context)

        # 6. Persist immutable evidence.
        persisted: list[Evidence] = []
        for ev in raw_evidence:
            persisted.append(c.evidence_service.add_evidence(ev))

        # 7. Update learner state per evidence (neutral signal: no task catalog).
        updated_states = []
        for ev in persisted:
            update = c.update_service.apply_evidence(ev, 1.0)
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
        from learner.traversal import direct_prerequisites

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

class EvidenceAssessor(Protocol):
    """Boundary for turning a learner message into structured evidence.

    A real implementation will be an LLM/rule system; the MVP ships only
    deterministic fakes (below) for tests and the replay harness.
    """

    def assess(
        self,
        learner_message: str,
        relevant_nodes: list[KnowledgeNode],
        conversation_context: dict,
    ) -> list[Evidence]:
        """Return structured evidence for the learner's message."""
        ...


class EvidenceSpec(dict):
    """A declarative evidence descriptor: keys map to Evidence fields, plus
    ``node_slug`` (resolved via the node resolver)."""


class RuleBasedEvidenceAssessor:
    """Deterministic keyword-rule assessor for tests.

    Each rule fires when ALL of its keywords appear in the (lowercased) message.
    A ``node_slug`` is resolved via ``node_resolver`` (slug -> id).
    """

    def __init__(self, rules: list[dict], node_resolver: Callable[[str], Optional[uuid.UUID]]) -> None:
        self._rules = rules
        self._resolve = node_resolver

    def assess(
        self,
        learner_message: str,
        relevant_nodes: list[KnowledgeNode],
        conversation_context: dict,
    ) -> list[Evidence]:
        lowered = learner_message.lower()
        evidence: list[Evidence] = []
        for rule in self._rules:
            if not all(kw in lowered for kw in rule["keywords"]):
                continue
            node_id = self._resolve(rule["node_slug"])
            if node_id is None:
                continue
            evidence.append(self._build(rule, node_id, conversation_context))
        return evidence

    @staticmethod
    def _build(rule: dict, node_id: uuid.UUID, context: dict) -> Evidence:
        return Evidence(
            learner_id=context.get("learner_id") or uuid.UUID(rule.get("learner_id", str(uuid.uuid4()))),
            node_id=node_id,
            evidence_type=EvidenceType(rule.get("evidence_type", "answer")),
            observation_status=ObservationStatus(rule.get("observation_status", "correct")),
            correctness=rule.get("correctness"),
            reasoning_quality=rule.get("reasoning_quality"),
            independence=rule.get("independence"),
            confidence=rule.get("confidence"),
            observed_behavior=rule.get("observed_behavior"),
            assessor_explanation=rule.get("assessor_explanation"),
            assessment_payload=rule.get("assessment_payload") or {},
        )


class ScriptedEvidenceAssessor:
    """Returns evidence from a fixed script, one entry per assessment call."""

    def __init__(self, script: list[list[dict]], node_resolver: Callable[[str], Optional[uuid.UUID]]) -> None:
        self._script = script
        self._resolve = node_resolver
        self._index = 0

    def assess(
        self,
        learner_message: str,
        relevant_nodes: list[KnowledgeNode],
        conversation_context: dict,
    ) -> list[Evidence]:
        if self._index >= len(self._script):
            return []
        specs = self._script[self._index]
        self._index += 1
        out: list[Evidence] = []
        for spec in specs:
            node_id = self._resolve(spec["node_slug"])
            if node_id is None:
                continue
            out.append(RuleBasedEvidenceAssessor._build(
                {k: v for k, v in spec.items() if k != "node_slug"},
                node_id, conversation_context,
            ))
        return out
