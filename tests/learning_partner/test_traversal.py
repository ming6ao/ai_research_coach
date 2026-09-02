"""Traversal utilities: prerequisites, dependents, neighbors, descendants, ancestors."""

from core.learning_partner.domain.types import EdgeType
from tests.conftest import make_edge, make_node


def _build_chain(service):
    """probability -> weighted_distribution -> normalize_weights (pure chain)."""
    p = service.create_node(make_node("probability"))
    w = service.create_node(make_node("weighted_distribution"))
    n = service.create_node(make_node("normalize_weights"))
    service.create_edge(make_edge(p, w, EdgeType.PREREQUISITE_OF))
    service.create_edge(make_edge(w, n, EdgeType.PREREQUISITE_OF))
    return p, w, n


class TestDirect:
    def test_direct_prerequisites(self, service):
        p, w, n = _build_chain(service)
        assert [x.slug for x in service.direct_prerequisites(w.id)] == ["probability"]
        assert [x.slug for x in service.direct_prerequisites(n.id)] == ["weighted_distribution"]

    def test_requires_edge_marks_source_as_prerequisite(self, service):
        # normalize_weights REQUIRES probability => probability is a prerequisite of normalize_weights
        p = service.create_node(make_node("probability"))
        n = service.create_node(make_node("normalize_weights"))
        service.create_edge(make_edge(n, p, EdgeType.REQUIRES))
        assert [x.slug for x in service.direct_prerequisites(n.id)] == ["probability"]
        assert [x.slug for x in service.direct_dependents(p.id)] == ["normalize_weights"]

    def test_direct_dependents(self, service):
        p, w, n = _build_chain(service)
        assert [x.slug for x in service.direct_dependents(p.id)] == ["weighted_distribution"]
        assert [x.slug for x in service.direct_dependents(w.id)] == ["normalize_weights"]
        assert service.direct_dependents(n.id) == []

    def test_neighbors_all_edge_types(self, service):
        p = service.create_node(make_node("probability"))
        w = service.create_node(make_node("weighted_distribution"))
        service.create_edge(make_edge(p, w, EdgeType.PREREQUISITE_OF))
        service.create_edge(make_edge(p, w, EdgeType.ENABLES))  # parallel, non-dependency edge

        nbrs = service.neighbors(p.id)
        assert [x.slug for x in nbrs] == ["weighted_distribution"]
        assert [x.slug for x in service.neighbors(w.id)] == ["probability"]


class TestDepth:
    def test_descendants(self, service):
        p, w, n = _build_chain(service)
        assert [x.slug for x in service.descendants(p.id, max_depth=1)] == ["weighted_distribution"]
        assert [x.slug for x in service.descendants(p.id, max_depth=2)] == [
            "normalize_weights",
            "weighted_distribution",
        ]
        assert [x.slug for x in service.descendants(p.id)] == [
            "normalize_weights",
            "weighted_distribution",
        ]
        assert service.descendants(n.id) == []

    def test_ancestors(self, service):
        p, w, n = _build_chain(service)
        assert [x.slug for x in service.ancestors(n.id, max_depth=1)] == ["weighted_distribution"]
        assert [x.slug for x in service.ancestors(n.id, max_depth=2)] == [
            "probability",
            "weighted_distribution",
        ]
        assert [x.slug for x in service.ancestors(n.id)] == [
            "probability",
            "weighted_distribution",
        ]
        assert service.ancestors(p.id) == []

    def test_descendants_respect_max_depth_none(self, service):
        a = service.create_node(make_node("a"))
        b = service.create_node(make_node("b"))
        c = service.create_node(make_node("c"))
        d = service.create_node(make_node("d"))
        service.create_edge(make_edge(a, b, EdgeType.PREREQUISITE_OF))
        service.create_edge(make_edge(b, c, EdgeType.PREREQUISITE_OF))
        service.create_edge(make_edge(c, d, EdgeType.PREREQUISITE_OF))

        assert [x.slug for x in service.descendants(a.id, max_depth=2)] == ["b", "c"]
        assert [x.slug for x in service.descendants(a.id)] == ["b", "c", "d"]

    def test_cycle_is_handled(self, service):
        a = service.create_node(make_node("a"))
        b = service.create_node(make_node("b"))
        service.create_edge(make_edge(a, b, EdgeType.PREREQUISITE_OF))
        service.create_edge(make_edge(b, a, EdgeType.PREREQUISITE_OF))
        assert [x.slug for x in service.descendants(a.id)] == ["b"]
        assert [x.slug for x in service.ancestors(b.id)] == ["a"]

    def test_related_nodes_via_service(self, service):
        p, w, n = _build_chain(service)
        assert {x.slug for x in service.get_related_nodes(w.id)} == {
            "probability",
            "normalize_weights",
        }