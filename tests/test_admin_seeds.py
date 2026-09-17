"""Admin-authored seed questions: POST /admin/seeds + GET /admin/taxonomy."""

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import coach.db as db

ADMIN = "gaomingduke@gmail.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "admin-seeds.db")
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    from backend.main import app

    return TestClient(app)


def _login(email, name="T"):
    user = auth.upsert_google_user(email, name)
    return auth.create_token(user["id"])


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_payload(**overrides):
    body = {
        "prompt": "Implement a function that returns the median of a list.",
        "difficulty": 2,
        "max_score": 5,
        "tags": {"primary": "linear_algebra", "secondary": ["probability_statistics"]},
        "task_type": "implement",
    }
    body.update(overrides)
    return body


def test_admin_seed_endpoints_require_auth(client):
    assert client.get("/admin/taxonomy").status_code == 401
    assert client.post("/admin/seeds", json=_seed_payload()).status_code == 401


def test_non_admin_is_forbidden(client):
    token = _login("mallory@x.com")
    assert client.get("/admin/taxonomy", headers=_h(token)).status_code == 403
    assert client.post("/admin/seeds", json=_seed_payload(), headers=_h(token)).status_code == 403


def test_taxonomy_endpoint(client):
    admin = _login(ADMIN)
    res = client.get("/admin/taxonomy", headers=_h(admin))
    assert res.status_code == 200
    data = res.json()
    assert "research" in data["domains"]
    assert "flash_attention" in data["areas"]["kernels_and_gpu"]
    assert set(data["task_types"]) == {"implement", "apply", "debug", "design", "analyze"}


def test_admin_creates_seed(client):
    from coach.tasks import get_task

    admin = _login(ADMIN)
    res = client.post("/admin/seeds", json=_seed_payload(), headers=_h(admin))
    assert res.status_code == 200
    task = res.json()["data"]
    assert task["id"].startswith("seed_admin_")
    assert task["owner"] == "system"
    assert task["source"] == "seed_admin"
    assert task["is_public"] is True
    assert task["tags"] == {"primary": "linear_algebra", "secondary": ["probability_statistics"]}
    assert task["context_notes"], "context notes auto-generated (deterministic fallback)"

    stored = get_task(task["id"])
    assert stored["owner"] == "system"
    assert stored["source"] == "seed_admin"

    # Visible to any candidate (public system-owned row).
    alice = _login("alice@x.com")
    listed = client.get("/api/v1/tasks?page_size=100", headers=_h(alice)).json()["data"]
    assert any(t["id"] == task["id"] for t in listed)


def test_admin_seed_with_explicit_context_notes(client):
    admin = _login(ADMIN)
    res = client.post(
        "/admin/seeds",
        json=_seed_payload(context_notes="A is a prerequisite of B, often confused with C."),
        headers=_h(admin),
    )
    assert res.status_code == 200
    assert res.json()["data"]["context_notes"] == "A is a prerequisite of B, often confused with C."


def test_admin_seed_rejects_unknown_tags(client):
    admin = _login(ADMIN)
    res = client.post(
        "/admin/seeds",
        json=_seed_payload(tags={"primary": "not_a_real_tag", "secondary": []}),
        headers=_h(admin),
    )
    assert res.status_code == 422


def test_admin_seed_rejects_empty_prompt(client):
    admin = _login(ADMIN)
    res = client.post("/admin/seeds", json=_seed_payload(prompt="   "), headers=_h(admin))
    assert res.status_code == 422


def test_admin_seed_rejects_invalid_task_type(client):
    admin = _login(ADMIN)
    res = client.post(
        "/admin/seeds", json=_seed_payload(task_type="speak"), headers=_h(admin)
    )
    assert res.status_code == 422