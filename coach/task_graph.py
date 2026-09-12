"""Per-task frozen knowledge graphs, stored on the task row.

Each task carries its own small graph (``tasks.graph_json``) frozen at
creation time. The graph is strictly per-task: node ``key`` values (``n0``,
``n1``, ...) are scoped to the owning ``task_id`` and mapped to global
``knowledge_nodes`` rows via a task-namespaced UUID5 (see
``learner.graph.task_node_id_for``). Same concept names in different tasks
are intentionally different nodes: no cross-task mastery sharing.

Canonical storage is JSON. YAML is accepted once at the write boundary
(``from_yaml``) and immediately converted to the canonical JSON form; YAML
is never stored or returned.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from learner.types import EdgeType, NodeType

GRAPH_VERSION = 1
MAX_NODES = 12
MAX_EDGES = 16


class TaskGraphNode(BaseModel):
    """One node in a frozen per-task graph."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    type: NodeType
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    importance: float = Field(default=0.7, ge=0.0, le=1.0)

    @field_validator("key")
    @classmethod
    def _strip_key(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("node key must be non-empty")
        return v

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("node name must be non-empty")
        return v[:255]


class TaskGraphEdge(BaseModel):
    """One directed edge between frozen per-task node keys."""

    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(min_length=1, max_length=64)
    target_key: str = Field(min_length=1, max_length=64)
    edge_type: EdgeType

    @model_validator(mode="after")
    def _no_self_edge(self) -> "TaskGraphEdge":
        if self.source_key == self.target_key:
            raise ValueError("self-edges are not allowed")
        return self


class TaskGraph(BaseModel):
    """Frozen per-task graph: validated once at creation, reused verbatim."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=GRAPH_VERSION, ge=1)
    primary_node_key: str = Field(min_length=1, max_length=64)
    nodes: list[TaskGraphNode] = Field(min_length=1, max_length=MAX_NODES)
    edges: list[TaskGraphEdge] = Field(default_factory=list, max_length=MAX_EDGES)

    @model_validator(mode="after")
    def _check_refs(self) -> "TaskGraph":
        keys = [n.key for n in self.nodes]
        if len(set(keys)) != len(keys):
            raise ValueError("node keys must be unique")
        by_key = set(keys)
        if self.primary_node_key not in by_key:
            raise ValueError(f"primary_node_key {self.primary_node_key!r} not in nodes")
        seen: set[tuple[str, str, str]] = set()
        for e in self.edges:
            if e.source_key not in by_key or e.target_key not in by_key:
                raise ValueError(
                    f"edge {e.source_key!r}->{e.target_key!r} references unknown node key"
                )
            triple = (e.source_key, e.target_key, e.edge_type.value)
            if triple in seen:
                raise ValueError(f"duplicate edge {triple}")
            seen.add(triple)
        return self

    # -- serialization ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "primary_node_key": self.primary_node_key,
            "nodes": [
                {
                    "key": n.key,
                    "type": n.type.value,
                    "name": n.name,
                    "description": n.description,
                    "importance": n.importance,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source_key": e.source_key,
                    "target_key": e.target_key,
                    "edge_type": e.edge_type.value,
                }
                for e in self.edges
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskGraph":
        if not isinstance(payload, dict):
            raise ValueError("graph payload must be a mapping")
        return cls.model_validate(payload)

    @classmethod
    def from_json(cls, raw: str) -> "TaskGraph":
        try:
            payload = json.loads(raw or "{}")
        except Exception as exc:
            raise ValueError(f"invalid graph JSON: {exc}") from exc
        return cls.from_dict(payload)

    @classmethod
    def from_yaml(cls, raw: str) -> "TaskGraph":
        """Parse YAML once at the write boundary; result is canonicalized to JSON."""
        try:
            import yaml  # local import: only needed on the YAML write path
        except ImportError as exc:
            raise ValueError("PyYAML is required to accept graph_yaml") from exc
        try:
            payload = yaml.safe_load(raw or "")
        except Exception as exc:
            raise ValueError(f"invalid graph YAML: {exc}") from exc
        if payload is None:
            raise ValueError("empty graph YAML")
        return cls.from_dict(payload)

    # -- TaskKnowledge interop ---------------------------------------------

    @classmethod
    def from_task_knowledge(cls, knowledge) -> "TaskGraph":
        """Freeze a decomposer ``TaskKnowledge`` into a storable graph."""
        return cls(
            version=GRAPH_VERSION,
            primary_node_key=knowledge.primary_node_key,
            nodes=[
                TaskGraphNode(
                    key=n.key,
                    type=n.type,
                    name=n.name,
                    description=n.description,
                    importance=max(0.0, min(1.0, float(n.importance))),
                )
                for n in knowledge.nodes
            ],
            edges=[
                TaskGraphEdge(
                    source_key=e.source_key,
                    target_key=e.target_key,
                    edge_type=e.edge_type,
                )
                for e in knowledge.edges
            ],
        )

    def to_task_knowledge(self, task_id: str, skill: str):
        """Rehydrate the decomposer-equivalent structure from frozen storage."""
        from coach.task_decomposer import DecomposedEdge, DecomposedNode, TaskKnowledge

        return TaskKnowledge(
            task_id=task_id,
            skill=skill,
            primary_node_key=self.primary_node_key,
            nodes=[
                DecomposedNode(
                    key=n.key,
                    type=n.type,
                    name=n.name,
                    description=n.description,
                    importance=n.importance,
                )
                for n in self.nodes
            ],
            edges=[
                DecomposedEdge(
                    source_key=e.source_key,
                    target_key=e.target_key,
                    edge_type=e.edge_type,
                )
                for e in self.edges
            ],
        )


def load_frozen_graph(task: dict[str, Any]) -> Optional[TaskGraph]:
    """Return the frozen graph embedded in a task dict, or None if absent."""
    raw = (task or {}).get("graph")
    if raw is None:
        return None
    if isinstance(raw, TaskGraph):
        return raw
    if isinstance(raw, dict):
        if not raw:
            return None
        return TaskGraph.from_dict(raw)
    if isinstance(raw, str):
        if not raw.strip():
            return None
        return TaskGraph.from_json(raw)
    raise ValueError(f"unsupported graph payload type: {type(raw).__name__}")


def coerce_graph_payload(
    graph: dict[str, Any] | TaskGraph | None,
    graph_yaml: Optional[str] = None,
) -> Optional[TaskGraph]:
    """Validate caller-supplied graph input (JSON dict wins over YAML string)."""
    if graph is not None:
        if isinstance(graph, TaskGraph):
            return graph
        return TaskGraph.from_dict(graph)
    if graph_yaml is not None:
        if not graph_yaml.strip():
            raise ValueError("empty graph_yaml")
        return TaskGraph.from_yaml(graph_yaml)
    return None


def freeze_graph_for_task(task: dict[str, Any], decomposer=None) -> dict[str, Any]:
    """Decompose a task once and return the frozen graph dict for storage."""
    if decomposer is None:
        from coach.task_decomposer import TaskDecomposer

        decomposer = TaskDecomposer()
    knowledge = decomposer.decompose(task)
    return TaskGraph.from_task_knowledge(knowledge).to_dict()


def ensure_task_graph(task: dict[str, Any], decomposer=None) -> "TaskGraph":
    """Return the frozen graph for a task, freezing + persisting legacy rows.

    Tasks created before the ``graph_json`` column (or created when
    decomposition failed) carry ``{}``. This decomposes once, persists via
    ``coach.tasks.set_task_graph`` (best-effort), and updates the task dict
    in place so the caller reuses the frozen copy.
    """
    existing = load_frozen_graph(task)
    if existing is not None:
        return existing
    frozen_dict = freeze_graph_for_task(task, decomposer=decomposer)
    frozen = TaskGraph.from_dict(frozen_dict)
    task["graph"] = frozen_dict
    task_id = (task or {}).get("id")
    if task_id:
        try:
            from coach.tasks import set_task_graph

            set_task_graph(task_id, frozen)
        except Exception:
            pass
    return frozen


# ---------------------------------------------------------------------------
# CLI: python -m coach.task_graph backfill [--dry-run]
# ---------------------------------------------------------------------------


def backfill(dry_run: bool = False) -> dict[str, int]:
    """Freeze graphs for all legacy task rows carrying an empty graph.

    Idempotent: rows that already have a valid graph are skipped; invalid
    stored graphs are left untouched and counted as errors.
    """
    from coach.db import create_schema, learner_session
    from coach.tasks import TaskModel, set_task_graph, task_to_dict

    create_schema()
    from coach.task_decomposer import TaskDecomposer

    decomposer = TaskDecomposer()
    session = learner_session()
    try:
        from sqlalchemy import select

        rows = session.scalars(select(TaskModel)).all()
        tasks = [task_to_dict(m) for m in rows]
    finally:
        session.close()

    done = skipped = errors = 0
    for task in tasks:
        raw = (task.get("graph") or {})
        if raw:
            try:
                TaskGraph.from_dict(raw)
                skipped += 1
                continue
            except Exception:
                errors += 1
                continue
        try:
            frozen_dict = freeze_graph_for_task(task, decomposer=decomposer)
            if not dry_run:
                set_task_graph(task["id"], frozen_dict)
            done += 1
        except Exception:
            errors += 1
    return {"frozen": done, "skipped": skipped, "errors": errors}


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="coach.task_graph", description="Per-task frozen graph tools.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("backfill", help="freeze graphs for legacy task rows")
    p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "backfill":
        result = backfill(dry_run=args.dry_run)
        print(
            f"backfill: frozen={result['frozen']} "
            f"skipped={result['skipped']} errors={result['errors']}"
            + (" (dry run)" if args.dry_run else "")
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
