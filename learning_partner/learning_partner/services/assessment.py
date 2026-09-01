"""AssessmentService: application-level orchestration for assessment tasks/targets.

Responsibilities:
- Validate that referenced entities exist before persisting targets/tasks.
- Provide a convenience API for composing a task with its targets.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from ..domain.assessment import (
    AssessmentTarget,
    AssessmentTask,
    TargetRole,
    TaskType,
)
from ..domain.errors import NodeNotFoundError, TaskNotFoundError
from ..domain.interfaces import (
    AssessmentTargetRepository,
    AssessmentTaskRepository,
    KnowledgeGraphRepository,
)


class AssessmentService:
    def __init__(
        self,
        task_repository: AssessmentTaskRepository,
        target_repository: AssessmentTargetRepository,
        knowledge_repository: KnowledgeGraphRepository,
    ) -> None:
        self.task_repository = task_repository
        self.target_repository = target_repository
        self.knowledge_repository = knowledge_repository

    # -- tasks -------------------------------------------------------------

    def create_task(self, task: AssessmentTask) -> AssessmentTask:
        return self.task_repository.create_task(task)

    def get_task(self, task_id: uuid.UUID) -> AssessmentTask | None:
        return self.task_repository.get_task(task_id)

    def update_task(self, task_id: uuid.UUID, **changes: Any) -> AssessmentTask:
        return self.task_repository.update_task(task_id, **changes)

    def list_tasks(self, task_type: Optional[TaskType] = None) -> list[AssessmentTask]:
        return self.task_repository.list_tasks(task_type)

    def find_tasks_for_node(
        self, node_id: uuid.UUID, role: Optional[TargetRole] = None
    ) -> list[AssessmentTask]:
        return self.task_repository.find_tasks_for_node(node_id, role)

    # -- targets -------------------------------------------------------------

    def add_target(
        self,
        task_id: uuid.UUID,
        node_id: uuid.UUID,
        target_role: TargetRole,
        expected_signal_strength: float = 1.0,
        metadata: Optional[dict] = None,
    ) -> AssessmentTarget:
        """Attach a node to a task as a target, validating both references."""
        if self.task_repository.get_task(task_id) is None:
            raise TaskNotFoundError(task_id)
        if self.knowledge_repository.get_node(node_id) is None:
            raise NodeNotFoundError(node_id)
        return self.target_repository.add_target(
            AssessmentTarget(
                task_id=task_id,
                node_id=node_id,
                target_role=target_role,
                expected_signal_strength=expected_signal_strength,
                metadata=metadata or {},
            )
        )

    def remove_target(self, task_id: uuid.UUID, node_id: uuid.UUID) -> bool:
        return self.target_repository.remove_target(task_id, node_id)

    def list_targets_for_task(
        self, task_id: uuid.UUID, role: Optional[TargetRole] = None
    ) -> list[AssessmentTarget]:
        return self.target_repository.list_targets_for_task(task_id, role)

    def list_tasks_targeting_node(
        self, node_id: uuid.UUID, role: Optional[TargetRole] = None
    ) -> list[AssessmentTask]:
        return self.target_repository.list_tasks_targeting_node(node_id, role)