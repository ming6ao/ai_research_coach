"""EvidenceAssessor interface and deterministic fake implementations (Stage 9).

The tutor response is NOT responsible for modifying the learner model. The
sequence is: learner response -> evidence -> learner-model update -> policy ->
tutor response. The ``EvidenceAssessor`` produces the structured evidence that
drives the update.
"""

from __future__ import annotations

import uuid
from typing import Callable, Optional, Protocol

from ..domain.assessment import AssessmentTask
from ..domain.evidence import Evidence, EvidenceType, ObservationStatus
from ..domain.knowledge import KnowledgeNode


class EvidenceAssessor(Protocol):
    """Boundary for turning a learner message into structured evidence.

    A real implementation will be an LLM/rule system; the MVP ships only
    deterministic fakes (below) for tests and the replay harness.
    """

    def assess(
        self,
        learner_message: str,
        relevant_nodes: list[KnowledgeNode],
        assessment_task: Optional[AssessmentTask],
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
        assessment_task: Optional[AssessmentTask],
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
            session_id=context.get("session_id"),
            interaction_id=context.get("interaction_id"),
            assessment_task_id=context.get("assessment_task_id"),
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
        assessment_task: Optional[AssessmentTask],
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