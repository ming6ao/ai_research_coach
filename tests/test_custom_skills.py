"""Custom (DB-backed) leaf skills: the curator-open skill vocabulary.

The built-in taxonomy stays closed; signed-in curators may add new leaf skills
under an existing area. These tests cover the API, the live-taxonomy merge,
tag validation, and persistence across a reload.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import coach.db as db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "custom.db")
    from backend.main import app

    return TestClient(app)


def _login(email="curator@x.com", name="Curator"):
    user = auth.upsert_google_user(email, name)
    return auth.create_token(user["id"])


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_create_skill_requires_auth(client):
    res = client.post("/api/v1/taxonomy/skills", json={"skill": "x", "area": "math"})
    assert res.status_code == 401


def test_create_and_list_skill(client):
    token = _login()
    res = client.post(
        "/api/v1/taxonomy/skills",
        json={"skill": "Tensor Parallel Debugging", "area": "distributed_training"},
        headers=_h(token),
    )
    assert res.status_code == 201
    data = res.json()["data"]
    assert data == {
        "skill": "tensor_parallel_debugging",
        "area": "distributed_training",
        "domain": "systems",
    }

    # It now appears in the public vocabulary tree/flat list.
    tax = client.get("/api/v1/taxonomy").json()["data"]
    assert "tensor_parallel_debugging" in tax["skills"]
    assert "tensor_parallel_debugging" in tax["tree"]["systems"]["distributed_training"]

    listed = client.get("/api/v1/taxonomy/skills", headers=_h(token)).json()["data"]
    assert [s["skill"] for s in listed] == ["tensor_parallel_debugging"]


def test_skill_can_be_used_to_tag_a_task(client):
    token = _login()
    client.post(
        "/api/v1/taxonomy/skills",
        json={"skill": "custom_metric", "area": "evaluation"},
        headers=_h(token),
    )
    res = client.post(
        "/api/v1/tasks",
        json={
            "parts": [
                {
                    "key": "solution",
                    "prompt": "Implement custom_metric.",
                    "tags": {"primary": "custom_metric"},
                    "max_score": 5,
                    "difficulty": 2,
                    "scaffold": "def custom_metric():\n    # TODO: implement\n    pass\n",
                }
            ],
            "tags": {"primary": "custom_metric"},
        },
        headers=_h(token),
    )
    assert res.status_code == 201, res.text
    assert res.json()["data"]["tags"]["primary"] == "custom_metric"


def test_custom_skill_surfaces_in_home_task_counts(client):
    token = _login()
    client.post(
        "/api/v1/taxonomy/skills",
        json={"skill": "custom_metric", "area": "evaluation"},
        headers=_h(token),
    )
    client.post(
        "/api/v1/tasks",
        json={
            "parts": [
                {
                    "key": "solution",
                    "prompt": "Implement custom_metric.",
                    "tags": {"primary": "custom_metric"},
                    "max_score": 5,
                    "difficulty": 2,
                    "scaffold": "def custom_metric():\n    # TODO: implement\n    pass\n",
                }
            ],
            "tags": {"primary": "custom_metric"},
            "is_public": True,
        },
        headers=_h(token),
    )
    counts = client.get(
        "/api/v1/me/overview", headers={"X-Guest-Id": "custom-skill-guest"}
    ).json()["data"]["task_counts"]
    assert counts.get("custom_metric") == 1
    assert counts.get("evaluation") == 1
    assert counts.get("research") == 1


def test_unknown_area_and_collisions_rejected(client):
    token = _login()
    # ``ablations`` is a skill, not an area.
    assert (
        client.post(
            "/api/v1/taxonomy/skills",
            json={"skill": "new_thing", "area": "ablations"},
            headers=_h(token),
        ).status_code
        == 422
    )
    # Collides with a built-in leaf.
    assert (
        client.post(
            "/api/v1/taxonomy/skills",
            json={"skill": "flash_attention", "area": "kernels_and_gpu"},
            headers=_h(token),
        ).status_code
        == 422
    )
    # Malformed name.
    assert (
        client.post(
            "/api/v1/taxonomy/skills",
            json={"skill": "../etc/passwd", "area": "math"},
            headers=_h(token),
        ).status_code
        == 422
    )


def test_duplicate_same_area_is_idempotent(client):
    token = _login()
    body = {"skill": "custom_metric", "area": "evaluation"}
    first = client.post("/api/v1/taxonomy/skills", json=body, headers=_h(token))
    second = client.post("/api/v1/taxonomy/skills", json=body, headers=_h(token))
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["data"] == second.json()["data"]
    listed = client.get("/api/v1/taxonomy/skills", headers=_h(token)).json()["data"]
    assert len(listed) == 1


def test_delete_skill_removes_it_from_vocabulary(client):
    token = _login()
    client.post(
        "/api/v1/taxonomy/skills",
        json={"skill": "custom_metric", "area": "evaluation"},
        headers=_h(token),
    )
    assert (
        client.delete("/api/v1/taxonomy/skills/custom_metric", headers=_h(token)).status_code
        == 200
    )
    tax = client.get("/api/v1/taxonomy").json()["data"]
    assert "custom_metric" not in tax["skills"]
    assert client.delete("/api/v1/taxonomy/skills/custom_metric", headers=_h(token)).status_code == 404


def test_skills_persist_across_taxonomy_reload(client):
    """The DB row re-merges into the live vocabulary after a reset/reload."""
    from coach.custom_skills import reload_into_taxonomy
    from coach.taxonomy import LEAF_NODES, load_custom_skills

    token = _login()
    client.post(
        "/api/v1/taxonomy/skills",
        json={"skill": "custom_metric", "area": "evaluation"},
        headers=_h(token),
    )
    # Simulate a restart: drop runtime customs, then reload from the DB.
    load_custom_skills([])
    assert "custom_metric" not in LEAF_NODES
    reload_into_taxonomy(force=True)
    assert "custom_metric" in LEAF_NODES
