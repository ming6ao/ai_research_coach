"""Seed data: Weighted Sampling From Scratch."""

import pytest

from core.learning_partner.domain.types import EdgeType, NodeType
from core.learning_partner.seed.weighted_sampling import (
    EDGE_SPECS,
    NODE_SPECS,
    seed_weighted_sampling,
)


@pytest.fixture()
def seeded(repository):
    return seed_weighted_sampling(repository), repository


class TestSeedGraph:
    def test_all_nodes_created(self, seeded):
        stats, repo = seeded
        assert stats["nodes_created"] == len(NODE_SPECS)
        assert stats["edges_created"] == len(EDGE_SPECS)

    def test_required_nodes_exist(self, seeded):
        _, repo = seeded
        required = {
            "probability": NodeType.CONCEPT,
            "weighted_distribution": NodeType.CONCEPT,
            "cumulative_distribution": NodeType.CONCEPT,
            "prefix_sum": NodeType.CONCEPT,
            "uniform_random_variable": NodeType.CONCEPT,
            "sampling_with_replacement": NodeType.CONCEPT,
            "normalize_weights": NodeType.SKILL,
            "construct_cdf": NodeType.SKILL,
            "generate_uniform_sample": NodeType.SKILL,
            "map_sample_to_interval": NodeType.SKILL,
            "binary_search_cdf": NodeType.SKILL,
            "handle_boundaries": NodeType.SKILL,
            "analyze_sampling_complexity": NodeType.SKILL,
            "weighted_sampling_from_scratch": NodeType.PROBLEM,
        }
        for slug, ntype in required.items():
            node = repo.get_node_by_slug(slug)
            assert node is not None, f"missing node {slug}"
            assert node.type == ntype, f"node {slug} has type {node.type}, expected {ntype}"

    def test_required_edges_exist(self, seeded):
        _, repo = seeded
        problem = repo.get_node_by_slug("weighted_sampling_from_scratch")
        required_edges = [
            ("probability", "weighted_distribution", EdgeType.PREREQUISITE_OF),
            ("weighted_distribution", "normalize_weights", EdgeType.ENABLES),
            ("prefix_sum", "construct_cdf", EdgeType.ENABLES),
            ("uniform_random_variable", "map_sample_to_interval", EdgeType.ENABLES),
            ("construct_cdf", "map_sample_to_interval", EdgeType.ENABLES),
            ("normalize_weights", "probability", EdgeType.REQUIRES),
            ("weighted_sampling_from_scratch", "normalize_weights", EdgeType.REQUIRES),
            ("weighted_sampling_from_scratch", "construct_cdf", EdgeType.REQUIRES),
            ("weighted_sampling_from_scratch", "generate_uniform_sample", EdgeType.REQUIRES),
            ("weighted_sampling_from_scratch", "map_sample_to_interval", EdgeType.REQUIRES),
        ]
        for src_slug, tgt_slug, edge_type in required_edges:
            src = repo.get_node_by_slug(src_slug)
            tgt = repo.get_node_by_slug(tgt_slug)
            assert repo.get_edge(src.id, tgt.id, edge_type) is not None, (
                f"missing edge {src_slug} -> {tgt_slug} ({edge_type.value})"
            )

    def test_idempotent(self, seeded):
        stats, repo = seeded
        second = seed_weighted_sampling(repo)
        assert second["nodes_created"] == 0
        assert second["edges_created"] == 0
        assert stats["total_nodes"] == len(NODE_SPECS)
        assert stats["total_edges"] == len(EDGE_SPECS)

    def test_problem_prerequisites_via_traversal(self, service, repository):
        from core.learning_partner.seed import seed_weighted_sampling

        seed_weighted_sampling(repository)
        problem = service.get_node_by_slug("weighted_sampling_from_scratch")
        prereqs = service.direct_prerequisites(problem.id)
        slugs = {n.slug for n in prereqs}
        assert {
            "normalize_weights",
            "construct_cdf",
            "generate_uniform_sample",
            "map_sample_to_interval",
        } <= slugs

        # prefix_sum is a prerequisite-ancestor of cumulative_distribution
        cd = service.get_node_by_slug("cumulative_distribution")
        ancestors = service.ancestors(cd.id)
        assert {n.slug for n in ancestors} == {"prefix_sum"}

        # ... and an enables-ancestor of construct_cdf is NOT a prerequisite
        cdf = service.get_node_by_slug("construct_cdf")
        assert service.ancestors(cdf.id) == []