"""Shared enums and domain exceptions for the learner model."""

from __future__ import annotations

from enum import Enum
import uuid


class NodeType(str, Enum):
    """What a knowledge node represents."""

    CONCEPT = "concept"
    SKILL = "skill"
    PROCEDURE = "procedure"
    PROBLEM = "problem"
    STRATEGY = "strategy"
    MISCONCEPTION = "misconception"
    DOMAIN = "domain"


class EdgeType(str, Enum):
    """Semantics of a directed relationship between two knowledge nodes."""

    PREREQUISITE_OF = "prerequisite_of"
    REQUIRES = "requires"
    PART_OF = "part_of"
    COMPOSED_OF = "composed_of"
    APPLIED_IN = "applied_in"
    CONTRASTS_WITH = "contrasts_with"
    COMMONLY_CONFUSED_WITH = "commonly_confused_with"
    GENERALIZES_TO = "generalizes_to"
    SPECIALIZES_TO = "specializes_to"
    ENABLES = "enables"
    ALTERNATIVE_TO = "alternative_to"


class NodeStatus(str, Enum):
    """Lifecycle state of a knowledge node."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"

class KnowledgeGraphError(Exception):
    """Base class for all knowledge-graph domain errors."""


class DuplicateNodeError(KnowledgeGraphError):
    """A node with the same identity already exists."""

    def __init__(self, node_id: object) -> None:
        super().__init__(f"a node with id {node_id!r} already exists")
        self.node_id = node_id


class NodeNotFoundError(KnowledgeGraphError):
    """No node exists with the given id."""

    def __init__(self, node_id: uuid.UUID) -> None:
        super().__init__(f"no node with id {node_id}")
        self.node_id = node_id


class DuplicateEdgeError(KnowledgeGraphError):
    """An identical edge (source, target, edge_type) already exists."""

    def __init__(self, source: uuid.UUID, target: uuid.UUID, edge_type: str) -> None:
        super().__init__(
            f"edge {source} -> {target} ({edge_type}) already exists"
        )
        self.source = source
        self.target = target
        self.edge_type = edge_type


class SelfEdgeError(KnowledgeGraphError):
    """Edges from a node to itself are not allowed."""

    def __init__(self, node_id: uuid.UUID) -> None:
        super().__init__(f"self-edges are not allowed (node {node_id})")
        self.node_id = node_id


class NodeReferencedError(KnowledgeGraphError):
    """The node cannot be deleted because edges reference it."""

    def __init__(self, node_id: uuid.UUID, edge_count: int) -> None:
        super().__init__(
            f"node {node_id} cannot be deleted: {edge_count} edge(s) reference it"
        )
        self.node_id = node_id
        self.edge_count = edge_count


class LearnerNotFoundError(KnowledgeGraphError):
    """No learner exists with the given id."""

    def __init__(self, learner_id: uuid.UUID) -> None:
        super().__init__(f"no learner with id {learner_id}")
        self.learner_id = learner_id


class StateNotFoundError(KnowledgeGraphError):
    """No learner-knowledge state exists for the given learner and node."""

    def __init__(self, learner_id: uuid.UUID, node_id: uuid.UUID) -> None:
        super().__init__(f"no state for learner {learner_id} on node {node_id}")
        self.learner_id = learner_id
        self.node_id = node_id


class EvidenceNotFoundError(KnowledgeGraphError):
    """No evidence record exists with the given id."""

    def __init__(self, evidence_id: uuid.UUID) -> None:
        super().__init__(f"no evidence with id {evidence_id}")
        self.evidence_id = evidence_id


class DuplicateEvidenceError(KnowledgeGraphError):
    """An evidence record with the same id already exists (evidence is immutable)."""

    def __init__(self, evidence_id: uuid.UUID) -> None:
        super().__init__(f"evidence {evidence_id} already exists; records are immutable")
        self.evidence_id = evidence_id


class MisconceptionNotFoundError(KnowledgeGraphError):
    """No learner misconception exists with the given id."""

    def __init__(self, misconception_id: uuid.UUID) -> None:
        super().__init__(f"no misconception with id {misconception_id}")
        self.misconception_id = misconception_id


class NotMisconceptionNodeError(KnowledgeGraphError):
    """A node was expected to be of type misconception but is not."""

    def __init__(self, node_id: uuid.UUID) -> None:
        super().__init__(f"node {node_id} is not a misconception node")
        self.node_id = node_id
