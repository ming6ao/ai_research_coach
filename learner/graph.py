"""Knowledge graph: nodes/edges, traversal facade, and SQL persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from learner.types import (
    EdgeType,
    NodeStatus,
    NodeType,
    DuplicateEdgeError,
    DuplicateSlugError,
    NodeNotFoundError,
    NodeReferencedError,
    SelfEdgeError,
)
from learner.interfaces import KnowledgeGraphRepository
from learner import traversal
from sqlalchemy import (
    func,
    or_,
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


def utcnow() -> datetime:
    """Timezone-aware UTC now. Single source of truth for timestamps."""
    return datetime.now(timezone.utc)


class KnowledgeNode(BaseModel):
    """A node in the knowledge graph: a concept, skill, procedure, problem, strategy,
    misconception, or domain."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: NodeType
    slug: str
    name: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: NodeStatus = NodeStatus.ACTIVE
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KnowledgeEdge(BaseModel):
    """A directed relationship between two knowledge nodes.

    ``(source_node_id, target_node_id, edge_type)`` must be unique.
    ``weight`` is a strength/importance in [0, 1].
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    edge_type: EdgeType
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

class KnowledgeGraphService:
    def __init__(self, repository: KnowledgeGraphRepository) -> None:
        self.repository = repository

    # -- persistence (delegated to repository) --------------------------

    def create_node(self, node: KnowledgeNode) -> KnowledgeNode:
        return self.repository.create_node(node)

    def get_node(self, node_id: uuid.UUID) -> KnowledgeNode | None:
        return self.repository.get_node(node_id)

    def get_node_by_slug(self, slug: str) -> KnowledgeNode | None:
        return self.repository.get_node_by_slug(slug)

    def update_node(self, node_id: uuid.UUID, **changes: Any) -> KnowledgeNode:
        return self.repository.update_node(node_id, **changes)

    def delete_node(self, node_id: uuid.UUID, *, force: bool = False) -> bool:
        return self.repository.delete_node(node_id, force=force)

    def create_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge:
        return self.repository.create_edge(edge)

    def get_edge(
        self,
        source_node_id: uuid.UUID,
        target_node_id: uuid.UUID,
        edge_type: EdgeType,
    ) -> KnowledgeEdge | None:
        return self.repository.get_edge(source_node_id, target_node_id, edge_type)

    def get_outgoing_edges(self, node_id: uuid.UUID) -> list[KnowledgeEdge]:
        return self.repository.get_outgoing_edges(node_id)

    def get_incoming_edges(self, node_id: uuid.UUID) -> list[KnowledgeEdge]:
        return self.repository.get_incoming_edges(node_id)

    def get_related_nodes(self, node_id: uuid.UUID) -> list[KnowledgeNode]:
        return self.repository.get_related_nodes(node_id)

    # -- graph traversal (application logic) -----------------------------

    def direct_prerequisites(self, node_id: uuid.UUID) -> list[KnowledgeNode]:
        return traversal.direct_prerequisites(self.repository, node_id)

    def direct_dependents(self, node_id: uuid.UUID) -> list[KnowledgeNode]:
        return traversal.direct_dependents(self.repository, node_id)

    def neighbors(self, node_id: uuid.UUID) -> list[KnowledgeNode]:
        return traversal.neighbors(self.repository, node_id)

    def descendants(
        self, node_id: uuid.UUID, max_depth: int | None = None
    ) -> list[KnowledgeNode]:
        return traversal.descendants(self.repository, node_id, max_depth=max_depth)

    def ancestors(
        self, node_id: uuid.UUID, max_depth: int | None = None
    ) -> list[KnowledgeNode]:
        return traversal.ancestors(self.repository, node_id, max_depth=max_depth)

class SQLKnowledgeGraphRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # -- nodes ---------------------------------------------------------

    def create_node(self, node: KnowledgeNode) -> KnowledgeNode:
        existing = self.get_node_by_slug(node.slug)
        if existing is not None:
            raise DuplicateSlugError(node.slug)
        model = KnowledgeNodeModel(
            id=uid(node.id),
            type=node.type.value,
            slug=node.slug,
            name=node.name,
            description=node.description,
            meta=node.metadata,
            status=node.status.value,
            created_at=naive_utc(node.created_at),
            updated_at=naive_utc(node.updated_at),
        )
        self._session.add(model)
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise DuplicateSlugError(node.slug) from exc
        return self.get_node(node.id)

    def get_node(self, node_id: uuid.UUID) -> KnowledgeNode | None:
        model = self._session.get(KnowledgeNodeModel, uid(node_id))
        return self._to_node(model) if model else None

    def get_node_by_slug(self, slug: str) -> KnowledgeNode | None:
        model = self._session.scalar(
            select(KnowledgeNodeModel).where(KnowledgeNodeModel.slug == slug)
        )
        return self._to_node(model) if model else None

    def update_node(self, node_id: uuid.UUID, **changes: Any) -> KnowledgeNode:
        model = self._session.get(KnowledgeNodeModel, uid(node_id))
        if model is None:
            raise NodeNotFoundError(node_id)

        if "name" in changes:
            model.name = changes["name"]
        if "description" in changes:
            model.description = changes["description"]
        if "metadata" in changes:
            model.meta = changes["metadata"] or {}
        if "type" in changes:
            value = changes["type"]
            model.type = value.value if isinstance(value, NodeType) else str(value)
        if "status" in changes:
            value = changes["status"]
            model.status = value.value if isinstance(value, NodeStatus) else str(value)
        if "slug" in changes:
            new_slug = changes["slug"]
            if self.get_node_by_slug(new_slug) is not None:
                raise DuplicateSlugError(new_slug)
            model.slug = new_slug
        model.updated_at = naive_utc(datetime.now(timezone.utc))

        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise DuplicateSlugError(changes.get("slug", "")) from exc
        return self.get_node(node_id)

    def delete_node(self, node_id: uuid.UUID, *, force: bool = False) -> bool:
        model = self._session.get(KnowledgeNodeModel, uid(node_id))
        if model is None:
            return False

        edge_count = self._count_edges_for(node_id)
        if edge_count and not force:
            raise NodeReferencedError(node_id, edge_count)

        if force:
            for edge in self._edges_for(node_id):
                self._session.delete(edge)

        self._session.delete(model)
        self._session.commit()
        return True

    # -- edges ---------------------------------------------------------

    def create_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge:
        if edge.source_node_id == edge.target_node_id:
            raise SelfEdgeError(edge.source_node_id)
        if self.get_node(edge.source_node_id) is None or self.get_node(edge.target_node_id) is None:
            missing = [
                nid
                for nid in (edge.source_node_id, edge.target_node_id)
                if self.get_node(nid) is None
            ]
            raise NodeNotFoundError(missing[0])

        model = KnowledgeEdgeModel(
            id=uid(edge.id),
            source_node_id=uid(edge.source_node_id),
            target_node_id=uid(edge.target_node_id),
            edge_type=edge.edge_type.value,
            weight=edge.weight,
            meta=edge.metadata,
            created_at=naive_utc(edge.created_at),
        )
        self._session.add(model)
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise DuplicateEdgeError(edge.source_node_id, edge.target_node_id, edge.edge_type.value) from exc
        return self._to_edge(model)

    def get_edge(
        self,
        source_node_id: uuid.UUID,
        target_node_id: uuid.UUID,
        edge_type: EdgeType,
    ) -> KnowledgeEdge | None:
        model = self._session.scalar(
            select(KnowledgeEdgeModel).where(
                KnowledgeEdgeModel.source_node_id == uid(source_node_id),
                KnowledgeEdgeModel.target_node_id == uid(target_node_id),
                KnowledgeEdgeModel.edge_type == edge_type.value,
            )
        )
        return self._to_edge(model) if model else None

    def get_outgoing_edges(self, node_id: uuid.UUID) -> list[KnowledgeEdge]:
        models = self._session.scalars(
            select(KnowledgeEdgeModel)
            .where(KnowledgeEdgeModel.source_node_id == uid(node_id))
            .order_by(KnowledgeEdgeModel.edge_type)
        ).all()
        return [self._to_edge(m) for m in models]

    def get_incoming_edges(self, node_id: uuid.UUID) -> list[KnowledgeEdge]:
        models = self._session.scalars(
            select(KnowledgeEdgeModel)
            .where(KnowledgeEdgeModel.target_node_id == uid(node_id))
            .order_by(KnowledgeEdgeModel.edge_type)
        ).all()
        return [self._to_edge(m) for m in models]

    def get_related_nodes(self, node_id: uuid.UUID) -> list[KnowledgeNode]:
        """Nodes connected by any edge (either direction)."""
        nid = uid(node_id)
        models = self._session.scalars(
            select(KnowledgeNodeModel).where(
                or_(
                    KnowledgeNodeModel.id.in_(
                        select(KnowledgeEdgeModel.source_node_id).where(
                            KnowledgeEdgeModel.target_node_id == nid
                        )
                    ),
                    KnowledgeNodeModel.id.in_(
                        select(KnowledgeEdgeModel.target_node_id).where(
                            KnowledgeEdgeModel.source_node_id == nid
                        )
                    ),
                )
            ).order_by(KnowledgeNodeModel.name)
        ).all()
        return [self._to_node(m) for m in models]

    # -- helpers -------------------------------------------------------

    def _count_edges_for(self, node_id: uuid.UUID) -> int:
        nid = uid(node_id)
        return self._session.scalar(
            select(func.count(KnowledgeEdgeModel.id)).where(
                or_(
                    KnowledgeEdgeModel.source_node_id == nid,
                    KnowledgeEdgeModel.target_node_id == nid,
                )
            )
        ) or 0

    def _edges_for(self, node_id: uuid.UUID) -> list[KnowledgeEdgeModel]:
        nid = uid(node_id)
        return self._session.scalars(
            select(KnowledgeEdgeModel).where(
                or_(
                    KnowledgeEdgeModel.source_node_id == nid,
                    KnowledgeEdgeModel.target_node_id == nid,
                )
            )
        ).all()

    @staticmethod
    def _to_node(model: KnowledgeNodeModel) -> KnowledgeNode:
        return KnowledgeNode(
            id=uuid.UUID(model.id),
            type=NodeType(model.type),
            slug=model.slug,
            name=model.name,
            description=model.description,
            metadata=dict(model.meta or {}),
            status=NodeStatus(model.status),
            created_at=aware_utc(model.created_at),
            updated_at=aware_utc(model.updated_at),
        )

    @staticmethod
    def _to_edge(model: KnowledgeEdgeModel) -> KnowledgeEdge:
        return KnowledgeEdge(
            id=uuid.UUID(model.id),
            source_node_id=uuid.UUID(model.source_node_id),
            target_node_id=uuid.UUID(model.target_node_id),
            edge_type=EdgeType(model.edge_type),
            weight=model.weight,
            metadata=dict(model.meta or {}),
            created_at=aware_utc(model.created_at),
        )

class KnowledgeNodeModel(Base):
    __tablename__ = "knowledge_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class KnowledgeEdgeModel(Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_node_id",
            "target_node_id",
            "edge_type",
            name="uq_knowledge_edges_source_target_type",
        ),
        Index("ix_knowledge_edges_source", "source_node_id"),
        Index("ix_knowledge_edges_target", "target_node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id"), nullable=False
    )
    target_node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id"), nullable=False
    )
    edge_type: Mapped[str] = mapped_column(String(64), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
