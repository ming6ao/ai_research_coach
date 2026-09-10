"""SQLAlchemy implementations of the assessment repository boundaries.

Pure persistence. Cross-table lookups (tasks targeting a node) are done with
joins/subqueries; no assessment-domain logic lives here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.assessment import (
    AssessmentTarget,
    AssessmentTask,
    TargetRole,
    TaskType,
)
from ..domain.errors import DuplicateTargetError, TaskNotFoundError
from .converters import aware_utc, naive_utc, uid
from .models import AssessmentTargetModel, AssessmentTaskModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SQLAssessmentTaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_task(self, task: AssessmentTask) -> AssessmentTask:
        model = AssessmentTaskModel(
            id=uid(task.id),
            task_type=task.task_type.value,
            title=task.title,
            prompt=task.prompt,
            difficulty=task.difficulty,
            meta=task.metadata,
            created_at=naive_utc(task.created_at),
            updated_at=naive_utc(task.updated_at),
        )
        self._session.add(model)
        self._session.commit()
        return self.get_task(task.id)

    def get_task(self, task_id: uuid.UUID) -> AssessmentTask | None:
        model = self._session.get(AssessmentTaskModel, uid(task_id))
        return self._to_task(model) if model else None

    def update_task(self, task_id: uuid.UUID, **changes: Any) -> AssessmentTask:
        model = self._session.get(AssessmentTaskModel, uid(task_id))
        if model is None:
            raise TaskNotFoundError(task_id)
        if "task_type" in changes:
            value = changes["task_type"]
            model.task_type = value.value if isinstance(value, TaskType) else str(value)
        if "title" in changes:
            model.title = changes["title"]
        if "prompt" in changes:
            model.prompt = changes["prompt"]
        if "difficulty" in changes:
            model.difficulty = changes["difficulty"]
        if "metadata" in changes:
            model.meta = changes["metadata"] or {}
        model.updated_at = naive_utc(_now())
        self._session.commit()
        return self.get_task(task_id)

    def list_tasks(self, task_type: Optional[TaskType] = None) -> list[AssessmentTask]:
        stmt = select(AssessmentTaskModel)
        if task_type is not None:
            stmt = stmt.where(AssessmentTaskModel.task_type == task_type.value)
        stmt = stmt.order_by(AssessmentTaskModel.title)
        return [self._to_task(m) for m in self._session.scalars(stmt).all()]

    def find_tasks_for_node(
        self, node_id: uuid.UUID, role: Optional[TargetRole] = None
    ) -> list[AssessmentTask]:
        """Tasks that have a target on ``node_id`` (optionally of ``role``)."""
        nid = uid(node_id)
        target_ids = select(AssessmentTargetModel.task_id).where(
            AssessmentTargetModel.node_id == nid
        )
        if role is not None:
            target_ids = target_ids.where(
                AssessmentTargetModel.target_role == role.value
            )
        stmt = (
            select(AssessmentTaskModel)
            .where(AssessmentTaskModel.id.in_(target_ids))
            .order_by(AssessmentTaskModel.title)
        )
        return [self._to_task(m) for m in self._session.scalars(stmt).all()]

    @staticmethod
    def _to_task(model: AssessmentTaskModel) -> AssessmentTask:
        return AssessmentTask(
            id=uuid.UUID(model.id),
            task_type=TaskType(model.task_type),
            title=model.title,
            prompt=model.prompt,
            difficulty=model.difficulty,
            metadata=dict(model.meta or {}),
            created_at=aware_utc(model.created_at),
            updated_at=aware_utc(model.updated_at),
        )


class SQLAssessmentTargetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_target(self, target: AssessmentTarget) -> AssessmentTarget:
        existing = self._session.scalar(
            select(AssessmentTargetModel).where(
                AssessmentTargetModel.task_id == uid(target.task_id),
                AssessmentTargetModel.node_id == uid(target.node_id),
            )
        )
        if existing is not None:
            raise DuplicateTargetError(target.task_id, target.node_id)
        model = AssessmentTargetModel(
            id=uid(target.id),
            task_id=uid(target.task_id),
            node_id=uid(target.node_id),
            target_role=target.target_role.value,
            expected_signal_strength=target.expected_signal_strength,
            meta=target.metadata,
            created_at=naive_utc(target.created_at),
            updated_at=naive_utc(target.updated_at),
        )
        self._session.add(model)
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise DuplicateTargetError(target.task_id, target.node_id) from exc
        return self._to_target(model)

    def remove_target(self, task_id: uuid.UUID, node_id: uuid.UUID) -> bool:
        model = self._session.scalar(
            select(AssessmentTargetModel).where(
                AssessmentTargetModel.task_id == uid(task_id),
                AssessmentTargetModel.node_id == uid(node_id),
            )
        )
        if model is None:
            return False
        self._session.delete(model)
        self._session.commit()
        return True

    def list_targets_for_task(
        self, task_id: uuid.UUID, role: Optional[TargetRole] = None
    ) -> list[AssessmentTarget]:
        stmt = select(AssessmentTargetModel).where(
            AssessmentTargetModel.task_id == uid(task_id)
        )
        if role is not None:
            stmt = stmt.where(AssessmentTargetModel.target_role == role.value)
        stmt = stmt.order_by(AssessmentTargetModel.expected_signal_strength.desc())
        return [self._to_target(m) for m in self._session.scalars(stmt).all()]

    def list_tasks_targeting_node(
        self, node_id: uuid.UUID, role: Optional[TargetRole] = None
    ) -> list[AssessmentTask]:
        """Tasks that target ``node_id`` (optionally with the given role)."""
        nid = uid(node_id)
        target_ids = select(AssessmentTargetModel.task_id).where(
            AssessmentTargetModel.node_id == nid
        )
        if role is not None:
            target_ids = target_ids.where(
                AssessmentTargetModel.target_role == role.value
            )
        stmt = (
            select(AssessmentTaskModel)
            .where(AssessmentTaskModel.id.in_(target_ids))
            .order_by(AssessmentTaskModel.title)
        )
        return [
            SQLAssessmentTaskRepository._to_task(m)
            for m in self._session.scalars(stmt).all()
        ]

    @staticmethod
    def _to_target(model: AssessmentTargetModel) -> AssessmentTarget:
        return AssessmentTarget(
            id=uuid.UUID(model.id),
            task_id=uuid.UUID(model.task_id),
            node_id=uuid.UUID(model.node_id),
            target_role=TargetRole(model.target_role),
            expected_signal_strength=model.expected_signal_strength,
            metadata=dict(model.meta or {}),
            created_at=aware_utc(model.created_at),
            updated_at=aware_utc(model.updated_at),
        )