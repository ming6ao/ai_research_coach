"""Test fixtures: deterministic knowledge graph used by learner-model tests.

Ports the old ``core.learner.seed`` package into the test tree (the app no
longer ships seed machinery). Idempotent seeder functions build a small
"Weighted Sampling From Scratch" graph, an assessment task, and a
misconception node for the learner-model / orchestrator tests.
"""

from __future__ import annotations

from typing import Any

from core.learner.domain.assessment import (
    AssessmentTarget,
    AssessmentTask,
    TargetRole,
    TaskType,
)
from core.learner.domain.interfaces import (
    AssessmentTargetRepository,
    AssessmentTaskRepository,
    KnowledgeGraphRepository,
)
from core.learner.domain.knowledge import KnowledgeEdge, KnowledgeNode
from core.learner.domain.types import EdgeType, NodeType

CDF_MISCONCEPTION_SLUG = "cdf_is_normalized_weights"

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


TASK_SLUG = "weighted_sampling_from_scratch"

TASK_SPEC = {
    "task_type": TaskType.CODING,
    "title": "Implement weighted sampling from scratch",
    "prompt": (
        "Implement weighted sampling from scratch: normalize weights to "
        "probabilities, build cumulative distribution, sample with replacement."
    ),
    "difficulty": 0.65,
}

# (node_slug, target_role, expected_signal_strength)
TARGET_SPECS: list[tuple[str, TargetRole, float]] = [
    ("normalize_weights", TargetRole.PRIMARY, 1.0),
    ("construct_cdf", TargetRole.PRIMARY, 1.0),
    ("generate_uniform_sample", TargetRole.PRIMARY, 0.9),
    ("map_sample_to_interval", TargetRole.PRIMARY, 1.0),
    ("sampling_with_replacement", TargetRole.PRIMARY, 0.9),
    ("handle_boundaries", TargetRole.DIAGNOSTIC, 0.7),
    ("binary_search_cdf", TargetRole.SECONDARY, 0.6),
    ("analyze_sampling_complexity", TargetRole.SECONDARY, 0.6),
]


def seed_weighted_sampling_task(
    task_repository: AssessmentTaskRepository,
    target_repository: AssessmentTargetRepository,
    knowledge_repository: KnowledgeGraphRepository,
) -> dict:
    """Create the seed task and its targets. Returns counts created."""
    seed_weighted_sampling(knowledge_repository)

    node_ids: dict[str, Any] = {}
    for slug, _, _ in TARGET_SPECS:
        node = knowledge_repository.get_node_by_slug(slug)
        if node is None:
            raise ValueError(f"seed node {slug!r} missing from knowledge graph")
        node_ids[slug] = node.id

    task = _find_task_by_slug(task_repository)
    task_created = task is None
    if task is None:
        task = task_repository.create_task(
            AssessmentTask(
                task_type=TASK_SPEC["task_type"],
                title=TASK_SPEC["title"],
                prompt=TASK_SPEC["prompt"],
                difficulty=TASK_SPEC["difficulty"],
                metadata={"slug": TASK_SLUG},
            )
        )

    created_targets = 0
    for slug, role, strength in TARGET_SPECS:
        node_id = node_ids[slug]
        existing = target_repository.list_targets_for_task(task.id)
        if not any(t.node_id == node_id for t in existing):
            target_repository.add_target(
                AssessmentTarget(
                    task_id=task.id,
                    node_id=node_id,
                    target_role=role,
                    expected_signal_strength=strength,
                )
            )
            created_targets += 1

    return {
        "task_created": task_created,
        "targets_created": created_targets,
        "task_id": str(task.id),
        "total_targets": len(TARGET_SPECS),
    }


def _find_task_by_slug(task_repository: AssessmentTaskRepository):
    for task in task_repository.list_tasks():
        if task.metadata.get("slug") == TASK_SLUG:
            return task
    return None


MISCONCEPTION_NODES: list[tuple[str, NodeType, str, str]] = [
    (
        CDF_MISCONCEPTION_SLUG,
        NodeType.MISCONCEPTION,
        "CDF is just the normalized probability array",
        "The learner believes the cumulative distribution function is simply the "
        "normalized weights, ignoring that it must accumulate probabilities.",
    ),
]


def seed_misconceptions(repo: KnowledgeGraphRepository) -> dict:
    created = 0
    for slug, ntype, name, description in MISCONCEPTION_NODES:
        if repo.get_node_by_slug(slug) is None:
            repo.create_node(
                KnowledgeNode(type=ntype, slug=slug, name=name, description=description)
            )
            created += 1
    return {"misconception_nodes_created": created, "total": len(MISCONCEPTION_NODES)}