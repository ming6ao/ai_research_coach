"""SQLAlchemy implementation of the KnowledgeGraphRepository boundary.

Pure CRUD and relationship lookups. All validation/business rules live in the
domain layer; the repository only enforces invariants that must hold in the DB
(uniqueness) and returns domain objects.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.errors import (
    DuplicateEdgeError,
    DuplicateSlugError,
    NodeNotFoundError,
    NodeReferencedError,
    SelfEdgeError,
)
from ..domain.knowledge import KnowledgeEdge, KnowledgeNode
from ..domain.types import EdgeType, NodeStatus, NodeType
from .converters import aware_utc, naive_utc, uid
from .models import KnowledgeEdgeModel, KnowledgeNodeModel


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
            version=node.version,
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
        if "version" in changes:
            model.version = changes["version"]
        else:
            model.version += 1
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
            version=model.version,
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