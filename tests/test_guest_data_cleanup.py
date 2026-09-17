"""Guest-data cleanup: preview + delete (admin-only)."""

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import coach.db as db
from coach.tasks import create_task

ADMIN = "gaomingduke@gmail.com"
NON_ADMIN = "mallory@x.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "cleanup.db")
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    from backend.main import app

    return TestClient(app)


def _login(email, name="T"):
    user = auth.upsert_google_user(email, name)
    return auth.create_token(user["id"])


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_guest_data_requires_admin(client):
    user = _login(NON_ADMIN)
    assert client.get("/admin/guest-data/preview", headers=_h(user)).status_code == 403
    assert client.delete("/admin/guest-data", headers=_h(user)).status_code == 403
    assert client.get("/admin/guest-data/preview").status_code == 401


def test_guest_data_delete_keeps_signed_in_user(client):
    admin = _login(ADMIN)
    create_task(
        owner="guest-abc",
        source="user",
        is_public=False,
        tags={"primary": "testing"},
        task_id="guest_task",
        parts=[{"key": "solution", "prompt": "Guest-owned task",
                "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2}],
    )
    create_task(
        owner=ADMIN,
        source="user",
        is_public=False,
        tags={"primary": "testing"},
        task_id="owner_task",
        parts=[{"key": "solution", "prompt": "Signed-in owned task",
                "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2}],
    )
    from coach.tasks import save_skill_belief

    save_skill_belief("guest-abc", 0.6, 0.1, 2)
    save_skill_belief(ADMIN, 0.7, 0.1, 3)

    preview = client.get("/admin/guest-data/preview", headers=_h(admin)).json()
    assert preview["counts"]["ability_beliefs"] == 1
    assert preview["counts"]["owned_tasks"] == 1
    assert preview["preview"] is True

    res = client.delete("/admin/guest-data", headers=_h(admin))
    assert res.status_code == 200
    data = res.json()
    assert data["counts"] == {
        "sessions": 0,
        "session_steps": 0,
        "ability_beliefs": 1,
        "owned_tasks": 1,
    }

    from coach.tasks import get_task

    assert get_task("guest_task") is None
    assert get_task("owner_task") is not None