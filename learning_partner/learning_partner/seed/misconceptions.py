"""Seed misconception node: "CDF is just the normalized probability array".

Idempotent. Adds a knowledge-graph node of type ``misconception`` used by the
Stage 6 misconception tests and the Stage 9/10 orchestrator scenarios.
"""

from __future__ import annotations

from ..domain.interfaces import KnowledgeGraphRepository
from ..domain.knowledge import KnowledgeNode
from ..domain.types import NodeType

CDF_MISCONCEPTION_SLUG = "cdf_is_normalized_weights"

NODES: list[tuple[str, NodeType, str, str]] = [
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
    for slug, ntype, name, description in NODES:
        if repo.get_node_by_slug(slug) is None:
            repo.create_node(
                KnowledgeNode(type=ntype, slug=slug, name=name, description=description)
            )
            created += 1
    return {"misconception_nodes_created": created, "total": len(NODES)}