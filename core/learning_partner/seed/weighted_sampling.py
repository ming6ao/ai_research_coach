"""Seed graph: "Weighted Sampling From Scratch".

Idempotent: nodes are looked up by slug and edges by (source, target, type), so
running the seeder more than once adds nothing.
"""

from __future__ import annotations

from typing import Any

from ..domain.interfaces import KnowledgeGraphRepository
from ..domain.knowledge import KnowledgeEdge, KnowledgeNode
from ..domain.types import EdgeType, NodeType

NODE_SPECS: list[tuple[str, NodeType, str, str]] = [
    # concepts
    ("probability", NodeType.CONCEPT, "Probability",
     "The measure of likelihood that an event occurs; foundation of sampling."),
    ("weighted_distribution", NodeType.CONCEPT, "Weighted Distribution",
     "A probability distribution over discrete outcomes with non-uniform weights."),
    ("cumulative_distribution", NodeType.CONCEPT, "Cumulative Distribution",
     "A CDF mapping each outcome to the cumulative probability up to it."),
    ("prefix_sum", NodeType.CONCEPT, "Prefix Sum",
     "An array where each entry is the sum of all entries before it."),
    ("uniform_random_variable", NodeType.CONCEPT, "Uniform Random Variable",
     "A random variable with equal probability over an interval, e.g. U[0, 1)."),
    ("sampling_with_replacement", NodeType.CONCEPT, "Sampling With Replacement",
     "Drawing items such that the same item may be drawn multiple times."),
    # skills
    ("normalize_weights", NodeType.SKILL, "Normalize Weights",
     "Scale weights so they sum to 1, forming a valid probability distribution."),
    ("construct_cdf", NodeType.SKILL, "Construct CDF",
     "Build a cumulative distribution from normalized weights (via prefix sums)."),
    ("generate_uniform_sample", NodeType.SKILL, "Generate Uniform Sample",
     "Produce a uniform random value in [0, 1) from a random source."),
    ("map_sample_to_interval", NodeType.SKILL, "Map Sample to Interval",
     "Translate a uniform sample into an outcome using the CDF."),
    ("binary_search_cdf", NodeType.SKILL, "Binary Search CDF",
     "Find the outcome interval for a sample by binary searching the prefix sums."),
    ("handle_boundaries", NodeType.SKILL, "Handle Boundaries",
     "Correctly handle zero weights, empty input, and end-of-CDF cases."),
    ("analyze_sampling_complexity", NodeType.SKILL, "Analyze Sampling Complexity",
     "Reason about time/space complexity of the weighted sampling algorithm."),
    # problems
    ("weighted_sampling_from_scratch", NodeType.PROBLEM, "Weighted Sampling From Scratch",
     "Implement weighted sampling using only weights and a uniform random source."),
]

EDGE_SPECS: list[tuple[str, str, EdgeType]] = [
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
    # supporting relationships for a richer graph
    ("prefix_sum", "cumulative_distribution", EdgeType.PREREQUISITE_OF),
    ("handle_boundaries", "binary_search_cdf", EdgeType.ENABLES),
    ("binary_search_cdf", "map_sample_to_interval", EdgeType.ENABLES),
]


def seed_weighted_sampling(repo: KnowledgeGraphRepository) -> dict:
    """Create the seed graph. Returns counts of created nodes/edges."""
    node_ids: dict[str, Any] = {}
    created_nodes = 0
    for slug, ntype, name, description in NODE_SPECS:
        node = repo.get_node_by_slug(slug)
        if node is None:
            node = repo.create_node(
                KnowledgeNode(type=ntype, slug=slug, name=name, description=description)
            )
            created_nodes += 1
        node_ids[slug] = node.id

    created_edges = 0
    for source_slug, target_slug, edge_type in EDGE_SPECS:
        source_id = node_ids[source_slug]
        target_id = node_ids[target_slug]
        existing = repo.get_edge(source_id, target_id, edge_type)
        if existing is None:
            repo.create_edge(
                KnowledgeEdge(
                    source_node_id=source_id,
                    target_node_id=target_id,
                    edge_type=edge_type,
                )
            )
            created_edges += 1

    return {"nodes_created": created_nodes, "edges_created": created_edges,
            "total_nodes": len(NODE_SPECS), "total_edges": len(EDGE_SPECS)}