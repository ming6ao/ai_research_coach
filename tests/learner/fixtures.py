"""Test fixtures: deterministic knowledge graph used by learner-model tests.

Ports the old ``learner`` package into the test tree (the app no
longer ships seed machinery). Idempotent seeder functions build a small
"Weighted Sampling From Scratch" graph and a
misconception node for the learner-model / orchestrator tests.

Node identity is deterministic: ``node_id_for(type, name)``. The first
element of each spec is a short test alias (kept stable so tests stay
readable); the display ``name`` is the identity input.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from learner.interfaces import (
    KnowledgeGraphRepository,
)
from learner.graph import KnowledgeEdge, KnowledgeNode, node_id_for
from learner.types import EdgeType, NodeType

CDF_MISCONCEPTION_NAME = "CDF is just the normalized probability array"

NODE_SPECS: list[tuple[str, NodeType, str, str]] = [
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
    ("prefix_sum", "cumulative_distribution", EdgeType.PREREQUISITE_OF),
    ("handle_boundaries", "binary_search_cdf", EdgeType.ENABLES),
    ("binary_search_cdf", "map_sample_to_interval", EdgeType.ENABLES),
]

_SPECS_BY_ALIAS: dict[str, tuple[NodeType, str, str]] = {
    alias: (ntype, name, description) for alias, ntype, name, description in NODE_SPECS
}


def node_id(alias: str) -> uuid.UUID:
    """Deterministic node id for a seed-graph alias."""
    ntype, name, _ = _SPECS_BY_ALIAS[alias]
    return node_id_for(ntype, name)


def get_node(repo: KnowledgeGraphRepository, alias: str) -> Optional[KnowledgeNode]:
    """Fetch a seed-graph node by its test alias."""
    return repo.get_node(node_id(alias))


def seed_weighted_sampling(repo: KnowledgeGraphRepository) -> dict:
    """Create the seed graph. Returns counts of created nodes/edges."""
    node_ids: dict[str, Any] = {}
    created_nodes = 0
    for alias, ntype, name, description in NODE_SPECS:
        nid = node_id_for(ntype, name)
        node = repo.get_node(nid)
        if node is None:
            node = repo.create_node(
                KnowledgeNode(id=nid, type=ntype, name=name, description=description)
            )
            created_nodes += 1
        node_ids[alias] = node.id

    created_edges = 0
    for source_alias, target_alias, edge_type in EDGE_SPECS:
        source_id = node_ids[source_alias]
        target_id = node_ids[target_alias]
        if repo.get_edge(source_id, target_id, edge_type) is None:
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


TASK_NAME = "Weighted Sampling From Scratch"


MISCONCEPTION_NODES: list[tuple[NodeType, str, str]] = [
    (
        NodeType.MISCONCEPTION,
        CDF_MISCONCEPTION_NAME,
        "The learner believes the cumulative distribution function is simply the "
        "normalized weights, ignoring that it must accumulate probabilities.",
    ),
]


def misconception_node_id() -> uuid.UUID:
    return node_id_for(NodeType.MISCONCEPTION, CDF_MISCONCEPTION_NAME)


def seed_misconceptions(repo: KnowledgeGraphRepository) -> dict:
    created = 0
    for ntype, name, description in MISCONCEPTION_NODES:
        nid = node_id_for(ntype, name)
        if repo.get_node(nid) is None:
            repo.create_node(
                KnowledgeNode(id=nid, type=ntype, name=name, description=description)
            )
            created += 1
    return {"misconception_nodes_created": created, "total": len(MISCONCEPTION_NODES)}
