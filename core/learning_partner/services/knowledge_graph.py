"""KnowledgeGraphService: application-level facade.

Composes the repository (persistence) and the traversal helpers (graph logic)
behind a single, simple API. Callers (seed scripts, future learners/evidence
stages, API layer) depend on this rather than the repository directly.
"""

from __future__ import annotations

import uuid
from typing import Any

from ..domain.interfaces import KnowledgeGraphRepository
from ..domain.knowledge import KnowledgeEdge, KnowledgeNode
from ..domain.types import EdgeType
from . import traversal


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