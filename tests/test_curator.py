"""Curator UI: my-tasks listing, public taxonomy, owner-or-admin writes."""

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import coach.db as db

ADMIN = "gaomingduke@gmail.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "curator.db")
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    from backend.main import app

    return TestClient(app)


def _login(email, name="T"):
    user = auth.upsert_google_user(email, name)
    return auth.create_token(user["id"])


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _create_owned(client, token, prompt, owner_email, is_public=True):
    res = client.post(
        "/api/v1/tasks",
        json={
            "prompt": prompt,
            "is_public": is_public,
            "tags": {"primary": "python", "secondary": []},
        },
        headers=_h(token),
    )
    assert res.status_code == 201, res.text
    task = res.json()["data"]
    assert task["owner"] == owner_email
    return task


def test_taxonomy_is_public(client):
    res = client.get("/api/v1/taxonomy")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["families"] and "python" in data["families"]
    assert "data_structures" in data["tags"]["python"]
    assert "implement" in data["task_types"]


def test_my_tasks_requires_auth(client):
    assert client.get("/api/v1/me/tasks").status_code == 401


def test_my_tasks_only_returns_own_rows_with_attempt_counts(client):
    alice = _login("alice@x.com")
    bob = _login("bob@x.com")

    alice_task = _create_owned(client, alice, "Alice's curated question", "alice@x.com")
    _create_owned(client, bob, "Bob's curated question", "bob@x.com", is_public=False)

    from coach.tasks import record_attempt

    record_attempt("alice@x.com", alice_task["id"], 0.8, 4, 5, [])

    res = client.get("/api/v1/me/tasks?page_size=100", headers=_h(alice))
    assert res.status_code == 200
    tasks = res.json()["data"]
    assert {t["owner"] for t in tasks} == {"alice@x.com"}
    assert any(t["id"] == alice_task["id"] and t["attempt_count"] == 1 for t in tasks)

    # Bob's private task stays hidden from Alice's list.
    bob_res = client.get("/api/v1/me/tasks?page_size=100", headers=_h(bob)).json()["data"]
    assert all(t["owner"] == "bob@x.com" for t in bob_res)


def test_my_tasks_search_and_pagination(client):
    token = _login("carol@x.com")
    for i in range(3):
        _create_owned(client, token, f"carol question {i}", "carol@x.com")

    page = client.get("/api/v1/me/tasks?q=carol%20question&page=1&page_size=2", headers=_h(token)).json()
    assert page["meta"]["total"] == 3
    assert len(page["data"]) == 2
    assert page["data"][0]["prompt"].startswith("carol question")

    no_hits = client.get("/api/v1/me/tasks?q=nope", headers=_h(token)).json()
    assert no_hits["meta"]["total"] == 0


def test_curator_can_edit_and_delete_own(client):
    token = _login("dave@x.com")
    task = _create_owned(client, token, "Before", "dave@x.com", is_public=True)

    res = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"prompt": "After", "difficulty": 4, "is_public": False},
        headers=_h(token),
    )
    assert res.status_code == 200
    assert res.json()["data"]["prompt"] == "After"
    assert res.json()["data"]["difficulty"] == 4
    assert res.json()["data"]["is_public"] is False

    deleted = client.delete(f"/api/v1/tasks/{task['id']}", headers=_h(token))
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 404


def test_admin_can_open_any_task_in_curator_editor(client):
    alice = _login("alice@x.com")
    admin = _login(ADMIN)
    task = _create_owned(client, alice, "Alice's task", "alice@x.com")

    # Admin reads any task by id (GET is visibility-agnostic) and edits it.
    got = client.get(f"/api/v1/tasks/{task['id']}", headers=_h(admin))
    assert got.status_code == 200
    assert got.json()["data"]["owner"] == "alice@x.com"

    res = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"context_notes": "edited by admin"},
        headers=_h(admin),
    )
    assert res.status_code == 200
    assert res.json()["data"]["context_notes"] == "edited by admin"


def test_curator_cannot_touch_others_tasks(client):
    alice = _login("alice@x.com")
    mallory = _login("mallory@x.com")
    task = _create_owned(client, alice, "Alice's task", "alice@x.com")

    assert client.patch(f"/api/v1/tasks/{task['id']}", json={"prompt": "x"}, headers=_h(mallory)).status_code == 403
    assert client.delete(f"/api/v1/tasks/{task['id']}", headers=_h(mallory)).status_code == 403


def test_owner_cannot_reassign_task(client):
    alice = _login("alice@x.com")
    bob = _login("bob@x.com")
    task = _create_owned(client, alice, "Alice's task", "alice@x.com")

    # The owner cannot reassign their own task to someone else.
    res = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"owner": "bob@x.com"},
        headers=_h(alice),
    )
    assert res.status_code == 403
    assert client.get(f"/api/v1/tasks/{task['id']}").json()["data"]["owner"] == "alice@x.com"


def test_admin_can_reassign_task_owner(client):
    alice = _login("alice@x.com")
    admin = _login(ADMIN)
    task = _create_owned(client, alice, "Alice's task", "alice@x.com")

    res = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"owner": "new-owner@x.com"},
        headers=_h(admin),
    )
    assert res.status_code == 200
    assert res.json()["data"]["owner"] == "new-owner@x.com"

    # The new owner sees it in their own list; the old owner no longer does.
    new_owner = _login("new-owner@x.com")
    theirs = client.get("/api/v1/me/tasks?page_size=100", headers=_h(new_owner)).json()["data"]
    assert any(t["id"] == task["id"] and t["owner"] == "new-owner@x.com" for t in theirs)
    old_owner = client.get("/api/v1/me/tasks?page_size=100", headers=_h(alice)).json()["data"]
    assert all(t["id"] != task["id"] for t in old_owner)


def test_admin_cannot_set_empty_owner(client):
    admin = _login(ADMIN)
    task = _create_owned(client, admin, "Admin task", ADMIN)

    res = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"owner": "   "},
        headers=_h(admin),
    )
    assert res.status_code == 422