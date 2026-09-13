"""Generic admin table browser: metadata + pagination/search + edit/delete."""

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import coach.db as db

ADMIN = "gaomingduke@gmail.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "tables.db")
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    from backend.main import app

    return TestClient(app)


def _login(email, name="T"):
    user = auth.upsert_google_user(email, name)
    return auth.create_token(user["id"])


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _seed(client_admin_headers):
    from backend.dependencies import get_store
    from coach.tasks import create_task, record_attempt, save_skill_belief

    store = get_store()
    sid = store.create("alice@x.com")
    store.save(sid, {"session": {"candidate": "alice@x.com"}})
    for i in range(3):
        create_task(prompt=f"Question {i} about fractions?", owner="alice@x.com")
    task = create_task(prompt="Bob's question?", owner="bob@x.com")
    record_attempt("alice@x.com", task["id"], 0.8, 4, 5, [])
    save_skill_belief("alice@x.com", 0.6, 0.1, 2)
    return task


def _seed_task_count():
    """Total tasks expected in the DB: builtin catalog + the _seed() rows."""
    from coach.seed_bank import SEED_CATALOG

    return len(SEED_CATALOG) + 4


def test_table_endpoints_require_auth(client):
    assert client.get("/admin/tables").status_code == 401
    assert client.get("/admin/table/tasks").status_code == 401
    assert client.get("/admin/whoami").status_code == 401


def test_table_endpoints_require_admin(client):
    user = _login("mallory@x.com")
    _seed(_h(user))
    assert client.get("/admin/tables", headers=_h(user)).status_code == 403
    assert client.get("/admin/table/tasks", headers=_h(user)).status_code == 403
    assert client.delete("/admin/table/tasks/x", headers=_h(user)).status_code == 403

    who = client.get("/admin/whoami", headers=_h(user)).json()
    assert who["is_admin"] is False


def test_whoami_and_tables_metadata(client):
    admin = _login(ADMIN)
    _seed(_h(admin))
    who = client.get("/admin/whoami", headers=_h(admin)).json()
    assert who["is_admin"] is True

    res = client.get("/admin/tables", headers=_h(admin))
    assert res.status_code == 200
    names = [t["name"] for t in res.json()["tables"]]
    assert names == ["users", "auth_tokens", "active_sessions", "tasks", "task_attempts", "user_skill_beliefs"]
    tasks_meta = next(t for t in res.json()["tables"] if t["name"] == "tasks")
    assert tasks_meta["count"] == _seed_task_count()
    assert tasks_meta["pk"] == "id"
    # Sensitive password_hash must never be exposed as a column.
    users_meta = next(t for t in res.json()["tables"] if t["name"] == "users")
    assert "password_hash" not in [c["name"] for c in users_meta["columns"]]


def test_pagination_and_search(client):
    admin = _login(ADMIN)
    headers = _h(admin)
    _seed(headers)

    page1 = client.get("/admin/table/tasks?page=1&page_size=2", headers=headers).json()
    assert page1["total"] == _seed_task_count()
    assert len(page1["rows"]) == 2
    assert page1["page"] == 1

    page2 = client.get("/admin/table/tasks?page=2&page_size=2", headers=headers).json()
    assert len(page2["rows"]) == 2
    assert {r["id"] for r in page1["rows"]} != {r["id"] for r in page2["rows"]}

    found = client.get("/admin/table/tasks?q=fractions", headers=headers).json()
    assert found["total"] == 3

    filtered = client.get("/admin/table/tasks?owner=bob@x.com", headers=headers).json()
    assert filtered["total"] == 1
    assert filtered["rows"][0]["prompt"] == "Bob's question?"

    assert client.get("/admin/table/nope", headers=headers).status_code == 404


def test_row_detail_edit_and_validation(client):
    from coach.tasks import get_task

    admin = _login(ADMIN)
    headers = _h(admin)
    bob_task = _seed(headers)

    detail = client.get(f"/admin/table/tasks/{bob_task['id']}", headers=headers).json()
    assert detail["row"]["prompt"] == "Bob's question?"
    assert client.get("/admin/table/tasks/does-not-exist", headers=headers).status_code == 404

    res = client.patch(
        f"/admin/table/tasks/{bob_task['id']}",
        json={"difficulty": 4, "context_notes": "notes here"},
        headers=headers,
    )
    assert res.status_code == 200
    assert get_task(bob_task["id"])["difficulty"] == 4

    # Invalid difficulty is rejected.
    bad = client.patch(
        f"/admin/table/tasks/{bob_task['id']}", json={"difficulty": 99}, headers=headers
    )
    assert bad.status_code == 400

    # Non-editable columns are rejected.
    bad2 = client.patch(
        f"/admin/table/tasks/{bob_task['id']}", json={"owner": "mallory@x.com"}, headers=headers
    )
    assert bad2.status_code == 400

    # Belief edit with range validation.
    beliefs = client.get("/admin/table/user_skill_beliefs?candidate=alice@x.com", headers=headers).json()
    bid = beliefs["rows"][0]["id"]
    res = client.patch(f"/admin/table/user_skill_beliefs/{bid}", json={"mean": 0.9}, headers=headers)
    assert res.status_code == 200
    assert res.json()["row"]["mean"] == 0.9
    assert client.patch(f"/admin/table/user_skill_beliefs/{bid}", json={"mean": 5}, headers=headers).status_code == 400

    # Read-only tables reject edits.
    sessions = client.get("/admin/table/active_sessions", headers=headers).json()
    sid = sessions["rows"][0]["session_id"]
    assert client.patch(f"/admin/table/active_sessions/{sid}", json={"candidate": "z"}, headers=headers).status_code == 400


def test_row_delete_with_cascade(client):
    from coach.tasks import get_task

    admin = _login(ADMIN)
    headers = _h(admin)
    bob_task = _seed(headers)

    res = client.delete(f"/admin/table/tasks/{bob_task['id']}", headers=headers)
    assert res.status_code == 200
    assert res.json()["deleted"] == 1
    assert get_task(bob_task["id"]) is None
    # The cascaded attempt is gone too.
    attempts = client.get("/admin/table/task_attempts", headers=headers).json()
    assert attempts["total"] == 0

    assert client.delete("/admin/table/tasks/does-not-exist", headers=headers).status_code == 404

    # Session row delete works.
    sessions = client.get("/admin/table/active_sessions", headers=headers).json()
    assert sessions["total"] == 1
    sid = sessions["rows"][0]["session_id"]
    assert client.delete(f"/admin/table/active_sessions/{sid}", headers=headers).status_code == 200
    assert client.get("/admin/table/active_sessions", headers=headers).json()["total"] == 0
