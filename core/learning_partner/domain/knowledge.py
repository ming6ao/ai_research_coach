"""Domain models for the knowledge graph.

These are pure Pydantic models. They know nothing about the database.
IDs are UUIDs; timestamps are timezone-aware UTC.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .types import EdgeType, NodeStatus, NodeType


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
    version: int = 1
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