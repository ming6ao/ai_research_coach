"""Assessment tasks/targets and SQL persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from learner.graph import utcnow
from learner.types import NodeNotFoundError, TaskNotFoundError, DuplicateTargetError
from learner.interfaces import (
    AssessmentTargetRepository,
    AssessmentTaskRepository,
    KnowledgeGraphRepository,
)
from sqlalchemy import (
    func,
    select,
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, Mapped, mapped_column
from coach.db import aware_utc, naive_utc, uid, Base


class TaskType(str, Enum):
    """The kind of activity an assessment task asks the learner to perform."""

    CODING = "coding"
    EXPLANATION = "explanation"
    DEBUGGING = "debugging"
    PREDICTION = "prediction"
    DESIGN = "design"
    MULTIPLE_CHOICE = "multiple_choice"
    TRACE = "trace"
    TEACH_BACK = "teach_back"


class TargetRole(str, Enum):
    """What role a knowledge node plays in an assessment task."""

    PRIMARY = "primary"          # the task directly measures this node
    SECONDARY = "secondary"      # exercised by the task, measured incidentally
    PREREQUISITE = "prerequisite"  # must be known for the task to be attempted
    DIAGNOSTIC = "diagnostic"    # probed to separate competing misconceptions


class AssessmentTask(BaseModel):
    """An assessment instrument given to a learner."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    task_type: TaskType
    title: str
    prompt: str
    difficulty: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AssessmentTarget(BaseModel):
    """Link from an assessment task to a knowledge node it exercises.

    ``(task_id, node_id)`` must be unique within a task. ``expected_signal_strength``
    is in [0, 1]: how strongly the task's outcome is expected to reveal the
    learner's ability on this node.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    task_id: uuid.UUID
    node_id: uuid.UUID
    target_role: TargetRole
    expected_signal_strength: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

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

def utcnow() -> datetime:
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
        model.updated_at = naive_utc(utcnow())
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

class AssessmentTaskModel(Base):
    __tablename__ = "assessment_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AssessmentTargetModel(Base):
    __tablename__ = "assessment_targets"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "node_id",
            name="uq_assessment_targets_task_node",
        ),
        Index("ix_assessment_targets_task", "task_id"),
        Index("ix_assessment_targets_node", "node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_tasks.id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id"), nullable=False
    )
    target_role: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_signal_strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
