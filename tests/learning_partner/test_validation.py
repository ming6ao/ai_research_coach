"""Validation rules: self-edges, referenced nodes, uniqueness, payload rules."""

import uuid

import pytest
from pydantic import ValidationError

from core.learning_partner.domain.errors import (
    DuplicateEdgeError,
    DuplicateSlugError,
    NodeNotFoundError,
    SelfEdgeError,
)
from core.learning_partner.domain.knowledge import KnowledgeEdge, KnowledgeNode
from core.learning_partner.domain.types import EdgeType, NodeType
from tests.conftest import make_edge, make_node


class TestEdgeValidation:
    def test_self_edge_blocked(self, repository):
        a = repository.create_node(make_node("a"))
        with pytest.raises(SelfEdgeError):
            repository.create_edge(make_edge(a, a, EdgeType.PART_OF))

    def test_edge_references_must_exist(self, repository):
        a = repository.create_node(make_node("a"))
        ghost = KnowledgeNode(type=NodeType.CONCEPT, slug="ghost", name="Ghost")
        with pytest.raises(NodeNotFoundError):
            repository.create_edge(make_edge(a, ghost, EdgeType.REQUIRES))

        other = repository.create_node(make_node("other"))
        with pytest.raises(NodeNotFoundError):
            repository.create_edge(make_edge(ghost, other, EdgeType.REQUIRES))

    def test_edge_uniqueness(self, repository):
        a = repository.create_node(make_node("a"))
        b = repository.create_node(make_node("b"))
        repository.create_edge(make_edge(a, b, EdgeType.REQUIRES))
        # Same endpoints, different type is allowed.
        repository.create_edge(make_edge(a, b, EdgeType.ENABLES))
        with pytest.raises(DuplicateEdgeError):
            repository.create_edge(make_edge(a, b, EdgeType.REQUIRES))

    def test_edge_weight_range(self):
        a = uuid.uuid4()
        b = uuid.uuid4()
        with pytest.raises(ValidationError):
            KnowledgeEdge(source_node_id=a, target_node_id=b, edge_type=EdgeType.REQUIRES, weight=1.5)
        with pytest.raises(ValidationError):
            KnowledgeEdge(source_node_id=a, target_node_id=b, edge_type=EdgeType.REQUIRES, weight=-0.1)
        KnowledgeEdge(source_node_id=a, target_node_id=b, edge_type=EdgeType.REQUIRES, weight=0.7)


class TestNodeValidation:
    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            KnowledgeNode(type=NodeType.CONCEPT, slug="x", name="X", bogus=True)

    def test_duplicate_slug_rejected(self, repository):
        repository.create_node(make_node("probability"))
        with pytest.raises(DuplicateSlugError):
            repository.create_node(make_node("probability"))

    def test_update_to_existing_slug_rejected(self, repository):
        a = repository.create_node(make_node("alpha"))
        repository.create_node(make_node("beta"))
        with pytest.raises(DuplicateSlugError):
            repository.update_node(a.id, slug="beta")