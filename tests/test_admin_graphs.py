"""Debug endpoints for per-task graphs: list, detail, regenerate, rebuild, stats."""

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import coach.db as db
from coach.task_graph import TaskGraph

ADMIN = "gaomingduke@gmail.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "graphs.db")
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from backend.main import app

    return TestClient(app)


def _login(email, name="T"):
    user = auth.upsert_google_user(email, name)
    return auth.create_token(user["id"])


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _graph_dict(name="Recursion"):
    return {
        "version": 1,
        "primary_node_key": "n0",
        "nodes": [
            {"key": "n0", "type": "skill", "name": name, "importance": 0.9},
            {"key": "n1", "type": "concept", "name": "Base Cases", "importance": 0.6},
        ],
        "edges": [
            {"source_key": "n1", "target_key": "n0", "edge_type": "prerequisite_of"},
        ],
    }


def _seed(owner="alice@x.com", task_id="g1", graph=True):
    from coach.tasks import create_task

    return create_task(
        prompt="Write fib.",
        skill="recursion",
        owner=owner,
        task_id=task_id,
        graph=_graph_dict() if graph else None,
    )


class TestTaskGraphEndpoints:
    def test_graphs_lists_frozen_tasks_only(self, client):
        token = _login("alice@x.com")
        _seed(task_id="g1", graph=True)
        _seed(task_id="g2", graph=False)

        res = client.get("/admin/graphs", headers=_h(token))
        assert res.status_code == 200
        ids = [g["task_id"] for g in res.json()["graphs"]]
        assert "g1" in ids
        assert "g2" not in ids
        entry = next(g for g in res.json()["graphs"] if g["task_id"] == "g1")
        assert entry["node_count"] == 2
        assert entry["edge_count"] == 1
        assert entry["primary_node_key"] == "n0"

    def test_task_graph_detail_returns_index_ids(self, client):
        from learner.graph import task_node_id_for

        token = _login("alice@x.com")
        _seed(task_id="g1", graph=True)

        res = client.get("/admin/tasks/g1/graph", headers=_h(token))
        assert res.status_code == 200
        body = res.json()
        assert body["frozen"] is True
        assert body["graph"]["primary_node_key"] == "n0"
        assert body["node_ids"]["n0"] == str(task_node_id_for("g1", "n0"))
        assert body["node_ids"]["n1"] == str(task_node_id_for("g1", "n1"))

    def test_task_graph_detail_unfrozen_and_missing(self, client):
        token = _login("alice@x.com")
        _seed(task_id="g2", graph=False)

        res = client.get("/admin/tasks/g2/graph", headers=_h(token))
        assert res.status_code == 200
        assert res.json()["frozen"] is False
        assert res.json()["graph"] is None

        assert client.get("/admin/tasks/nope/graph", headers=_h(token)).status_code == 404

    def test_regenerate_owner_ok_stranger_forbidden(self, client, monkeypatch):
        from coach.task_decomposer import DecomposedNode, TaskKnowledge
        from learner.types import NodeType

        token = _login("alice@x.com")
        stranger = _login("mallory@x.com")
        _seed(task_id="g1", graph=True)

        def fake_decompose(self, task):
            return TaskKnowledge(
                task_id=task["id"],
                skill=task.get("skill", "general"),
                primary_node_key="n0",
                nodes=[DecomposedNode(key="n0", type=NodeType.SKILL, name="Fresh", importance=1.0)],
                edges=[],
            )

        from coach.task_decomposer import TaskDecomposer

        monkeypatch.setattr(TaskDecomposer, "decompose", fake_decompose)

        assert client.post("/admin/tasks/g1/graph/regenerate", headers=_h(stranger)).status_code == 403
        res = client.post("/admin/tasks/g1/graph/regenerate", headers=_h(token))
        assert res.status_code == 200
        graph = res.json()["task"]["graph"]
        assert TaskGraph.from_dict(graph).nodes[0].name == "Fresh"

    def test_rebuild_requires_admin(self, client):
        from coach.admin import rebuild_graph_index

        user = _login("alice@x.com")
        admin = _login(ADMIN)
        _seed(task_id="g1", graph=True)

        assert client.post("/admin/graph/rebuild", headers=_h(user)).status_code == 403
        res = client.post("/admin/graph/rebuild", headers=_h(admin))
        assert res.status_code == 200
        assert res.json()["mirrored"] >= 1
        assert rebuild_graph_index()["mirrored"] >= 1

    def test_stats_and_summary_use_task_coverage(self, client):
        token = _login("alice@x.com")
        _seed(task_id="g1", graph=True)
        _seed(task_id="g2", graph=False)

        stats = client.get("/admin/stats", headers=_h(token)).json()
        assert stats["tasks_total"] == 2
        assert stats["tasks_frozen"] == 1
        assert stats["tasks_unfrozen"] == 1
        assert "knowledge_nodes" not in stats

        summary = client.get("/admin/graph/summary", headers=_h(token)).json()
        assert summary["tasks_frozen"] == 1
        assert summary["index_nodes"] >= 0

    def test_unauthenticated_is_401(self, client):
        assert client.get("/admin/graphs").status_code == 401
        assert client.get("/admin/tasks/g1/graph").status_code == 401
        assert client.post("/admin/graph/rebuild").status_code == 401
