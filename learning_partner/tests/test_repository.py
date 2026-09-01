from learning_partner.domain.knowledge import KnowledgeNode
from learning_partner.domain.types import NodeType
from tests.conftest import make_edge, make_node
import pytest

from learning_partner.domain.errors import (
    DuplicateEdgeError,
    DuplicateSlugError,
    NodeNotFoundError,
    NodeReferencedError,
    SelfEdgeError,
)
from tests.conftest import make_edge, make_node


class TestNodeCRUD:
    def test_create_and_get_node(self, repository):
        node = make_node("probability", NodeType.CONCEPT, "Probability")
        created = repository.create_node(node)
        assert created.id == node.id
        assert created.slug == "probability"

        fetched = repository.get_node(node.id)
        assert fetched == created
        assert fetched.type == NodeType.CONCEPT
        assert fetched.name == "Probability"

    def test_get_missing_node_returns_none(self, repository):
        import uuid

        assert repository.get_node(uuid.uuid4()) is None

    def test_get_node_by_slug(self, repository):
        node = repository.create_node(make_node("prefix_sum"))
        assert repository.get_node_by_slug("prefix_sum").id == node.id
        assert repository.get_node_by_slug("nope") is None

    def test_duplicate_slug_rejected(self, repository):
        repository.create_node(make_node("probability"))
        with pytest.raises(DuplicateSlugError):
            repository.create_node(make_node("probability"))

    def test_update_node(self, repository):
        node = repository.create_node(make_node("probability", name="Probability"))
        updated = repository.update_node(node.id, name="Probability v2", description="updated")
        assert updated.name == "Probability v2"
        assert updated.description == "updated"
        assert updated.version == node.version + 1
        assert updated.updated_at >= node.updated_at

    def test_update_missing_node_raises(self, repository):
        import uuid

        with pytest.raises(NodeNotFoundError):
            repository.update_node(uuid.uuid4(), name="x")

    def test_delete_node(self, repository):
        node = repository.create_node(make_node("probability"))
        assert repository.delete_node(node.id) is True
        assert repository.get_node(node.id) is None

    def test_delete_missing_node_returns_false(self, repository):
        import uuid

        assert repository.delete_node(uuid.uuid4()) is False


class TestEdgeCRUD:
    def test_create_and_get_edge(self, repository):
        a = repository.create_node(make_node("a"))
        b = repository.create_node(make_node("b"))
        from learning_partner.domain.types import EdgeType

        edge = repository.create_edge(
            make_edge(a, b, EdgeType.PREREQUISITE_OF)
        )
        fetched = repository.get_edge(a.id, b.id, EdgeType.PREREQUISITE_OF)
        assert fetched.id == edge.id

    def test_duplicate_edge_rejected(self, repository):
        from learning_partner.domain.types import EdgeType

        a = repository.create_node(make_node("a"))
        b = repository.create_node(make_node("b"))
        repository.create_edge(make_edge(a, b, EdgeType.PREREQUISITE_OF))
        with pytest.raises(DuplicateEdgeError):
            repository.create_edge(make_edge(a, b, EdgeType.PREREQUISITE_OF))

    def test_self_edge_rejected(self, repository):
        from learning_partner.domain.types import EdgeType

        a = repository.create_node(make_node("a"))
        with pytest.raises(SelfEdgeError):
            repository.create_edge(make_edge(a, a, EdgeType.PART_OF))

    def test_edge_to_missing_node_rejected(self, repository):
        from learning_partner.domain.types import EdgeType

        a = repository.create_node(make_node("a"))
        import uuid

        with pytest.raises(NodeNotFoundError):
            repository.create_edge(
                make_edge(a, KnowledgeNode(type=NodeType.CONCEPT, slug="ghost", name="Ghost"), EdgeType.REQUIRES)
            )

    def test_outgoing_and_incoming_edges(self, repository):
        from learning_partner.domain.types import EdgeType

        a = repository.create_node(make_node("a"))
        b = repository.create_node(make_node("b"))
        c = repository.create_node(make_node("c"))
        repository.create_edge(make_edge(a, b, EdgeType.PREREQUISITE_OF))
        repository.create_edge(make_edge(c, b, EdgeType.REQUIRES))

        outgoing = repository.get_outgoing_edges(a.id)
        assert [e.target_node_id for e in outgoing] == [b.id]

        incoming = repository.get_incoming_edges(b.id)
        assert sorted(e.source_node_id for e in incoming) == sorted([a.id, c.id])

    def test_get_related_nodes(self, repository):
        from learning_partner.domain.types import EdgeType

        a = repository.create_node(make_node("a"))
        b = repository.create_node(make_node("b"))
        c = repository.create_node(make_node("c"))
        repository.create_edge(make_edge(a, b, EdgeType.PREREQUISITE_OF))
        repository.create_edge(make_edge(c, b, EdgeType.REQUIRES))

        related = repository.get_related_nodes(b.id)
        assert {n.id for n in related} == {a.id, c.id}


class TestDeleteSafety:
    def test_delete_referenced_node_raises(self, repository):
        from learning_partner.domain.types import EdgeType

        a = repository.create_node(make_node("a"))
        b = repository.create_node(make_node("b"))
        repository.create_edge(make_edge(a, b, EdgeType.PREREQUISITE_OF))
        with pytest.raises(NodeReferencedError):
            repository.delete_node(a.id)
        assert repository.get_node(a.id) is not None

    def test_force_delete_removes_edges(self, repository):
        from learning_partner.domain.types import EdgeType

        a = repository.create_node(make_node("a"))
        b = repository.create_node(make_node("b"))
        repository.create_edge(make_edge(a, b, EdgeType.PREREQUISITE_OF))
        assert repository.delete_node(a.id, force=True) is True
        assert repository.get_node(a.id) is None
        assert repository.get_outgoing_edges(a.id) == []
        assert repository.get_incoming_edges(b.id) == []