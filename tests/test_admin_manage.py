"""Task ownership (v1 owner-or-admin guard) + candidate wipes."""

import uuid

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import coach.db as db

ADMIN = "gaomingduke@gmail.com"


def _record_step(candidate, task_id, fraction, score, max_score):
    """Seed one scored ``session_steps`` row for aggregation tests."""
    from coach.steps import insert_step

    return insert_step(
        session_id=f"seed-{uuid.uuid4().hex[:8]}",
        candidate=candidate,
        step_index=0,
        task={"id": task_id, "max_score": max_score},
        role="bank",
        user_answer="",
        score=score,
        max_score=max_score,
        fraction=fraction,
        reward=fraction,
        state_before=None,
        state_after=None,
        result={"score": score, "max_score": max_score},
        coaching=None,
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "admin.db")
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    from backend.main import app

    return TestClient(app)


def _login(email, name="T"):
    user = auth.upsert_google_user(email, name)
    return auth.create_token(user["id"])


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_candidate(candidate):
    """Seed one row per candidate-scoped table; return owned task id."""
    from backend.dependencies import get_store
    from coach.tasks import create_task, save_skill_belief

    store = get_store()
    sid = store.create(candidate)
    store.save(sid, {"session": {"candidate": candidate}})

    task = create_task(prompt="Owned question?", owner=candidate, tags={"primary": "testing"})
    _record_step(candidate, task["id"], 0.8, 4, 5)
    save_skill_belief(candidate, 0.6, 0.1, 1)
    return task["id"]


def test_unauthenticated_task_writes_are_401(client):
    # v1 task listing is public (seed + public rows); writes need auth.
    assert client.get("/api/v1/tasks").status_code == 200
    task_id = _seed_candidate("alice@x.com")
    assert client.patch(f"/api/v1/tasks/{task_id}", json={"context_notes": "x"}).status_code == 401
    assert client.delete(f"/api/v1/tasks/{task_id}").status_code == 401
    assert client.get("/admin/candidate/a@x.com/summary").status_code == 401
    assert client.delete("/admin/candidate/a@x.com").status_code == 401


def test_non_owner_non_admin_is_forbidden(client):
    mallory = _login("mallory@x.com")
    task_id = _seed_candidate("alice@x.com")

    assert client.get("/admin/candidate/alice@x.com/summary", headers=_h(mallory)).status_code == 403
    assert client.delete("/admin/candidate/alice@x.com", headers=_h(mallory)).status_code == 403
    assert client.patch(f"/api/v1/tasks/{task_id}", json={"context_notes": "x"}, headers=_h(mallory)).status_code == 403
    assert client.delete(f"/api/v1/tasks/{task_id}", headers=_h(mallory)).status_code == 403


def test_owner_can_wipe_self(client):
    token = _login("alice@x.com")
    _seed_candidate("alice@x.com")

    summary = client.get("/admin/candidate/alice@x.com/summary", headers=_h(token)).json()
    assert summary["active_sessions"] == 1
    assert summary["session_steps"] == 1
    assert summary["ability_beliefs"] == 1
    assert summary["owned_tasks"] == 1
    assert summary["total"] == 4

    res = client.delete("/admin/candidate/alice@x.com", headers=_h(token))
    assert res.status_code == 200
    assert res.json()["deleted"]["total"] == 4

    again = client.get("/admin/candidate/alice@x.com/summary", headers=_h(token)).json()
    assert again["total"] == 0


def test_admin_can_wipe_other_candidate_and_shared_task(client):
    from coach.tasks import create_task, get_task

    _seed_candidate("bob@x.com")
    shared_task = create_task(
        prompt="Shared bank question?", owner="bank@example.com",
        source="user", is_public=True, tags={"primary": "testing"},
    )
    _record_step("alice@x.com", shared_task["id"], 0.5, 2, 5)

    admin = _login(ADMIN)
    res = client.delete("/admin/candidate/bob@x.com", headers=_h(admin))
    assert res.status_code == 200
    assert res.json()["deleted"]["total"] > 0

    # Shared public row: admin-only delete with cascade of its steps.
    res = client.delete(f"/api/v1/tasks/{shared_task['id']}", headers=_h(admin))
    assert res.status_code == 200
    assert res.json()["data"] == {
        "task_id": shared_task["id"],
        "deleted_task": 1,
        "deleted_attempts": 1,
    }
    assert get_task(shared_task["id"]) is None


def test_task_owner_delete_cascades_attempts(client):
    from coach.tasks import create_task, get_task

    token = _login("carol@x.com")
    task = create_task(prompt="Carol's question?", owner="carol@x.com", tags={"primary": "testing"})

    _record_step("carol@x.com", task["id"], 1.0, 5, 5)

    listed = client.get("/api/v1/tasks?page_size=100", headers=_h(token)).json()["data"]
    assert any(t["id"] == task["id"] for t in listed)

    res = client.delete(f"/api/v1/tasks/{task['id']}", headers=_h(token))
    assert res.status_code == 200
    assert res.json()["data"]["deleted_task"] == 1
    assert res.json()["data"]["deleted_attempts"] == 1
    assert get_task(task["id"]) is None

    assert client.delete("/api/v1/tasks/does-not-exist", headers=_h(token)).status_code == 404


def test_task_owner_can_edit_context_notes(client):
    from coach.tasks import create_task, get_task

    token = _login("dave@x.com")
    stranger = _login("mallory@x.com")
    task = create_task(prompt="Dave's question?", owner="dave@x.com", tags={"primary": "testing"})

    res = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"context_notes": "A is a prerequisite of B, often confused with C."},
        headers=_h(token),
    )
    assert res.status_code == 200
    assert res.json()["data"]["context_notes"].startswith("A is a prerequisite")
    assert get_task(task["id"])["context_notes"].startswith("A is a prerequisite")

    assert client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"context_notes": "hijacked"},
        headers=_h(stranger),
    ).status_code == 403
    assert client.patch("/api/v1/tasks/does-not-exist", json={"context_notes": "x"}, headers=_h(token)).status_code == 404
