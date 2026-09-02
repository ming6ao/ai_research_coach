"""Graph traversal utilities.

All traversal is breadth-first over edges fetched from the repository, in
application code — never recursive SQL, so the database stays portable.

Prerequisite semantics (what must be known before X):
  - ``A --prerequisite_of--> X``: A is a prerequisite of X
  - ``X --requires--> A``:      A is a prerequisite of X

Dependent semantics (what depends on X):
  - ``X --prerequisite_of--> B``: B depends on X
  - ``B --requires--> X``:        B depends on X

Only ``prerequisite_of`` and ``requires`` edges participate in
prerequisites/dependents/ancestors/descendants. ``neighbors`` and
``get_related_nodes`` consider every edge type.
"""

from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Callable
from typing import TypeAlias

from ..domain.interfaces import KnowledgeGraphRepository
from ..domain.knowledge import KnowledgeNode
from ..domain.types import EdgeType

_NeighborFn: TypeAlias = Callable[[KnowledgeGraphRepository, uuid.UUID], set[uuid.UUID]]


def _predecessor_ids(repo: KnowledgeGraphRepository, node_id: uuid.UUID) -> set[uuid.UUID]:
    """Direct prerequisites of ``node_id`` (nodes that must be known first)."""
    ids: set[uuid.UUID] = set()
    for edge in repo.get_incoming_edges(node_id):
        if edge.edge_type == EdgeType.PREREQUISITE_OF:
            ids.add(edge.source_node_id)
    for edge in repo.get_outgoing_edges(node_id):
        if edge.edge_type == EdgeType.REQUIRES:
            ids.add(edge.target_node_id)
    return ids


def _successor_ids(repo: KnowledgeGraphRepository, node_id: uuid.UUID) -> set[uuid.UUID]:
    """Direct dependents of ``node_id`` (nodes that depend on it)."""
    ids: set[uuid.UUID] = set()
    for edge in repo.get_incoming_edges(node_id):
        if edge.edge_type == EdgeType.REQUIRES:
            ids.add(edge.source_node_id)
    for edge in repo.get_outgoing_edges(node_id):
        if edge.edge_type == EdgeType.PREREQUISITE_OF:
            ids.add(edge.target_node_id)
    return ids


def _ordered_nodes(
    repo: KnowledgeGraphRepository, node_ids: set[uuid.UUID]
) -> list[KnowledgeNode]:
    nodes = [n for n in (repo.get_node(nid) for nid in node_ids) if n is not None]
    return sorted(nodes, key=lambda n: n.slug)


def direct_prerequisites(
    repo: KnowledgeGraphRepository, node_id: uuid.UUID
) -> list[KnowledgeNode]:
    """Direct prerequisites of the node (one hop)."""
    return _ordered_nodes(repo, _predecessor_ids(repo, node_id))


def direct_dependents(
    repo: KnowledgeGraphRepository, node_id: uuid.UUID
) -> list[KnowledgeNode]:
    """Direct dependents of the node (one hop)."""
    return _ordered_nodes(repo, _successor_ids(repo, node_id))


def neighbors(repo: KnowledgeGraphRepository, node_id: uuid.UUID) -> list[KnowledgeNode]:
    """All directly connected nodes via any edge type, in either direction."""
    ids: set[uuid.UUID] = set()
    for edge in repo.get_outgoing_edges(node_id):
        ids.add(edge.target_node_id)
    for edge in repo.get_incoming_edges(node_id):
        ids.add(edge.source_node_id)
    return _ordered_nodes(repo, ids)


def _bfs(
    repo: KnowledgeGraphRepository,
    start_id: uuid.UUID,
    expand: _NeighborFn,
    max_depth: int | None,
) -> set[uuid.UUID]:
    """BFS returning node ids within ``max_depth`` hops (None = unlimited)."""
    visited: set[uuid.UUID] = {start_id}
    queue: deque[tuple[uuid.UUID, int]] = deque([(start_id, 0)])
    result: set[uuid.UUID] = set()
    while queue:
        current, depth = queue.popleft()
        if max_depth is not None and depth >= max_depth:
            continue
        for nid in expand(repo, current):
            if nid not in visited:
                visited.add(nid)
                result.add(nid)
                queue.append((nid, depth + 1))
    return result


def descendants(
    repo: KnowledgeGraphRepository,
    node_id: uuid.UUID,
    max_depth: int | None = None,
) -> list[KnowledgeNode]:
    """All nodes reachable along dependent edges, up to ``max_depth`` hops."""
    return _ordered_nodes(repo, _bfs(repo, node_id, _successor_ids, max_depth))


def ancestors(
    repo: KnowledgeGraphRepository,
    node_id: uuid.UUID,
    max_depth: int | None = None,
) -> list[KnowledgeNode]:
    """All nodes reachable along prerequisite edges, up to ``max_depth`` hops."""
    return _ordered_nodes(repo, _bfs(repo, node_id, _predecessor_ids, max_depth))