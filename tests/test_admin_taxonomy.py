"""Admin taxonomy vocabulary: GET /admin/taxonomy."""

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import coach.db as db

ADMIN = "gaomingduke@gmail.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "admin-taxonomy.db")
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    from backend.main import app

    return TestClient(app)


def _login(email, name="T"):
    user = auth.upsert_google_user(email, name)
    return auth.create_token(user["id"])


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_taxonomy_requires_auth(client):
    assert client.get("/admin/taxonomy").status_code == 401


def test_non_admin_is_forbidden(client):
    token = _login("mallory@x.com")
    assert client.get("/admin/taxonomy", headers=_h(token)).status_code == 403


def test_taxonomy_endpoint(client):
    admin = _login(ADMIN)
    res = client.get("/admin/taxonomy", headers=_h(admin))
    assert res.status_code == 200
    data = res.json()
    assert "research" in data["domains"]
    assert "flash_attention" in data["areas"]["kernels_and_gpu"]
    assert set(data["task_types"]) == {"implement", "apply", "debug", "design", "analyze"}
