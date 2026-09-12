"""Per-task frozen knowledge graphs: validation, freeze-once, namespacing."""

from __future__ import annotations

import pytest

import coach.db as db
from coach.task_graph import (
    TaskGraph,
    coerce_graph_payload,
    ensure_task_graph,
    freeze_graph_for_task,
    load_frozen_graph,
)
from learner.graph import task_misconception_id_for, task_node_id_for


def _valid_graph_dict() -> dict:
    return {
        "version": 1,
        "primary_node_key": "n0",
        "nodes": [
            {"key": "n0", "type": "skill", "name": "Binary Search", "importance": 0.9},
            {"key": "n1", "type": "concept", "name": "Loop Invariants", "importance": 0.6},
        ],
        "edges": [
            {"source_key": "n1", "target_key": "n0", "edge_type": "prerequisite_of"},
        ],
    }


class TestValidation:
    def test_valid_graph_round_trips(self):
        g = TaskGraph.from_dict(_valid_graph_dict())
        assert g.primary_node_key == "n0"
        assert g.to_dict()["nodes"][0]["name"] == "Binary Search"
        assert TaskGraph.from_json(g.to_json()) == g

    def test_rejects_dangling_primary(self):
        bad = _valid_graph_dict()
        bad["primary_node_key"] = "n9"
        with pytest.raises(ValueError):
            TaskGraph.from_dict(bad)

    def test_rejects_dangling_edge(self):
        bad = _valid_graph_dict()
        bad["edges"] = [{"source_key": "n1", "target_key": "n9", "edge_type": "requires"}]
        with pytest.raises(ValueError):
            TaskGraph.from_dict(bad)

    def test_rejects_self_edge(self):
        bad = _valid_graph_dict()
        bad["edges"] = [{"source_key": "n0", "target_key": "n0", "edge_type": "requires"}]
        with pytest.raises(ValueError):
            TaskGraph.from_dict(bad)

    def test_rejects_duplicate_keys(self):
        bad = _valid_graph_dict()
        bad["nodes"] = [bad["nodes"][0], dict(bad["nodes"][0])]
        with pytest.raises(ValueError):
            TaskGraph.from_dict(bad)

    def test_rejects_bad_enum(self):
        bad = _valid_graph_dict()
        bad["nodes"][0]["type"] = "vibes"
        with pytest.raises(ValueError):
            TaskGraph.from_dict(bad)

    def test_rejects_empty_nodes(self):
        bad = _valid_graph_dict()
        bad["nodes"] = []
        with pytest.raises(ValueError):
            TaskGraph.from_dict(bad)


class TestYamlBoundary:
    def test_yaml_accepted_and_canonicalized(self):
        raw = """
version: 1
primary_node_key: n0
nodes:
  - key: n0
    type: skill
    name: Binary Search  # comments allowed
    importance: 0.9
  - key: n1
    type: concept
    name: Loop Invariants
edges:
  - source_key: n1
    target_key: n0
    edge_type: prerequisite_of
"""
        g = TaskGraph.from_yaml(raw)
        assert g.primary_node_key == "n0"
        # Canonical form is JSON (no YAML stored or returned).
        assert '"Binary Search"' in g.to_json()

    def test_coerce_prefers_dict_over_yaml(self):
        g = coerce_graph_payload(_valid_graph_dict(), "primary_node_key: n0")
        assert isinstance(g, TaskGraph)

    def test_coerce_yaml_only(self):
        g = coerce_graph_payload(None, "primary_node_key: n0\nnodes: [{key: n0, type: skill, name: S}]\nedges: []")
        assert g.primary_node_key == "n0"

    def test_empty_yaml_rejected(self):
        with pytest.raises(ValueError):
            TaskGraph.from_yaml("   \n")


class TestNamespacing:
    def test_same_key_differs_per_task(self):
        assert task_node_id_for("task_a", "n0") != task_node_id_for("task_b", "n0")

    def test_same_key_stable_per_task(self):
        assert task_node_id_for("task_a", "n0") == task_node_id_for("task_a", "n0")

    def test_misconceptions_scoped_per_task(self):
        assert task_misconception_id_for("task_a", "oops") != task_misconception_id_for("task_b", "oops")


class TestFreezeHelpers:
    def test_freeze_uses_decomposer_once(self):
        from tests.test_learner_bridge import FakeDecomposer

        task = {"id": "t1", "skill": "ml_systems", "prompt": "Do it."}
        frozen = freeze_graph_for_task(task, decomposer=FakeDecomposer())
        g = TaskGraph.from_dict(frozen)
        assert g.primary_node_key == "n0"
        assert len(g.nodes) == 2

    def test_load_frozen_graph_absent(self):
        assert load_frozen_graph({"id": "x"}) is None
        assert load_frozen_graph({"id": "x", "graph": {}}) is None

    def test_ensure_task_graph_persists_legacy_row(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "coach.db")
        monkeypatch.setenv("LEARNING_PARTNER_DB_URL", f"sqlite:///{tmp_path}/learner.db")
        from tests.test_learner_bridge import FakeDecomposer
        from coach.tasks import create_task, get_task

        task = create_task(prompt="Legacy row?", skill="s", owner="a@x.com")
        assert task["graph"] == {}
        frozen = ensure_task_graph(task, decomposer=FakeDecomposer())
        assert frozen.primary_node_key == "n0"
        # Persisted to the row and embedded back on the dict.
        assert get_task(task["id"])["graph"]["primary_node_key"] == "n0"
        assert task["graph"]["primary_node_key"] == "n0"
        # Second call reuses the frozen copy without the decomposer.
        class Exploding:
            def decompose(self, task):
                raise AssertionError("must not re-decompose")

        assert ensure_task_graph(task, decomposer=Exploding()).primary_node_key == "n0"


class TestGeneratedChildGraph:
    def test_child_graph_valid_and_primary_is_concept(self):
        from coach.remediation import _child_graph_for_generated

        child = _child_graph_for_generated(
            {"id": "remed_1", "skill": "ml_systems"}, {"name": "Cache Eviction", "description": "d"}
        )
        g = TaskGraph.from_dict(child)
        assert g.primary_node_key == "n1"
        assert g.nodes[1].name == "Cache Eviction"

    def test_child_graph_none_without_name(self):
        from coach.remediation import _child_graph_for_generated

        assert _child_graph_for_generated({"id": "r", "skill": "s"}, {"name": ""}) is None


class TestBackfillCli:
    def test_backfill_freezes_legacy_rows(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "coach.db")
        monkeypatch.setenv("LEARNING_PARTNER_DB_URL", f"sqlite:///{tmp_path}/learner.db")
        # Ensure no API key so the hermetic fallback path is used.
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        from coach.tasks import create_task, get_task
        from coach.task_graph import backfill, main

        task = create_task(prompt="Old row?", skill="s", owner="a@x.com")
        assert get_task(task["id"])["graph"] == {}

        assert main(["backfill", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "frozen=1" in out
        # Dry run does not persist.
        assert get_task(task["id"])["graph"] == {}

        result = backfill()
        assert result == {"frozen": 1, "skipped": 0, "errors": 0}
        assert get_task(task["id"])["graph"]["primary_node_key"] == "n0"

    def test_admin_rebuild_mirrors_index(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "coach.db")
        monkeypatch.setenv("LEARNING_PARTNER_DB_URL", f"sqlite:///{tmp_path}/learner.db")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        from coach.tasks import create_task
        from coach.admin import clear_knowledge_graph, rebuild_graph_index

        create_task(
            prompt="Q?",
            skill="s",
            owner="a@x.com",
            task_id="rebuild_t1",
            graph=_valid_graph_dict(),
        )
        result = rebuild_graph_index()
        assert result["mirrored"] == 1
        cleared = clear_knowledge_graph()
        assert cleared["deleted"]["knowledge_nodes"] >= 2
        result = rebuild_graph_index()
        assert result["mirrored"] == 1
