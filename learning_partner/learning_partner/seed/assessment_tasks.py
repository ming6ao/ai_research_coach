"""Seed assessment task: "Implement weighted sampling from scratch".

Idempotent: the task is looked up by a stable ``metadata.slug``; targets are
looked up by (task_id, node_id). Re-running adds nothing.
"""

from __future__ import annotations

from typing import Any

from ..domain.assessment import (
    AssessmentTarget,
    AssessmentTask,
    TargetRole,
    TaskType,
)
from ..domain.interfaces import (
    AssessmentTargetRepository,
    AssessmentTaskRepository,
    KnowledgeGraphRepository,
)
from .weighted_sampling import seed_weighted_sampling

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
    # The graph must exist for the targets to reference real nodes.
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
        already = any(t.node_id == node_id for t in existing)
        if not already:
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