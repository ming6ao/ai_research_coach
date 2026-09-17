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
    """Total tasks expected in the DB: the _seed() rows only (no code catalog)."""
    return 4


def test_table_endpoints_require_auth(client):
    assert client.get("/admin/tables").status_code == 401
    assert client.get("/admin/table/tasks").status_code == 401
    assert client.get("/admin/whoami").status_code == 401


def test_reset_endpoints_require_admin(client):
    user = _login("mallory@x.com")
    _seed(_h(user))
    # Non-admin gets 403.
    assert client.get("/admin/reset/preview", headers=_h(user)).status_code == 403
    assert client.post("/admin/reset", headers=_h(user)).status_code == 403

    admin = _login(ADMIN)
    # Dry-run preview reports the activity rows (users/auth/tasks not wiped).
    preview = client.get("/admin/reset/preview", headers=_h(admin)).json()
    assert preview["preview"] is True
    assert "users" not in preview["wiped"]
    assert "tasks" not in preview["wiped"]  # task bank is preserved
    assert preview["total_deleted"] > 0

    # The real reset wipes activity but keeps the task bank + auth.
    res = client.post("/admin/reset", headers=_h(admin))
    assert res.status_code == 200
    body = res.json()
    assert body["preview"] is False
    assert body["wiped"]["active_sessions"] == 1  # the _seed() session
    assert body["wiped"]["session_steps"] == 1
    assert "tasks" in body["preserved"]
    tasks_meta = next(
        t for t in client.get("/admin/tables", headers=_h(admin)).json()["tables"]
        if t["name"] == "tasks"
    )
    assert tasks_meta["count"] == 4  # task bank survived the reset
    # Auth survived the reset.
    assert client.get("/admin/whoami", headers=_h(admin)).json()["is_admin"] is True


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
    assert names == ["users", "auth_tokens", "active_sessions", "tasks", "session_steps", "user_skill_beliefs"]
    tasks_meta = next(t for t in res.json()["tables"] if t["name"] == "tasks")
    assert tasks_meta["count"] == _seed_task_count()
    assert tasks_meta["pk"] == "id"
    # Sensitive password_hash must never be exposed as a column.
    users_meta = next(t for t in res.json()["tables"] if t["name"] == "users")
    assert "password_hash" not in [c["name"] for c in users_meta["columns"]]


def test_tasks_registry_exposes_parts_and_version_fields(client):
    from coach.tasks import create_task

    admin = _login(ADMIN)
    headers = _h(admin)
    _seed(headers)

    meta = client.get("/admin/tables", headers=headers).json()["tables"]
    tasks_meta = next(t for t in meta if t["name"] == "tasks")
    cols = {c["name"] for c in tasks_meta["columns"]}
    assert {"parts_json", "version_index", "depends_on_task_id", "version_root_id"} <= cols
    assert not ({"hints_json", "cluster_id", "followups_json"} & cols)

    # A block task carries parts and a successor carries version links.
    block = create_task(
        prompt="Block task?",
        owner="alice@x.com",
        task_id="block_01",
        parts=[{"key": "f", "prompt": "def f(): ...", "tags": {"primary": "python"},
                "max_score": 5, "difficulty": 2}],
    )
    create_task(
        prompt="Successor task?",
        owner="alice@x.com",
        task_id="block_01_v2",
        depends_on_task_id="block_01",
    )
    rows = client.get("/admin/table/tasks?page_size=100", headers=headers).json()["rows"]
    block_row = next(r for r in rows if r["id"] == "block_01")
    assert '"key": "f"' in block_row["parts_json"]
    successor_row = next(r for r in rows if r["id"] == "block_01_v2")
    assert successor_row["version_index"] == 2
    assert successor_row["depends_on_task_id"] == "block_01"

    detail = client.get("/admin/table/tasks/block_01", headers=headers).json()
    assert '"key": "f"' in detail["row"]["parts_json"]

    # Editable through the admin API (parts validated, version fields writable).
    created = create_task(
        prompt="New task?", owner="alice@x.com",
        parts=[{"key": "g", "prompt": "def g(): ...", "tags": {"primary": "python"},
                "max_score": 5, "difficulty": 2}],
    )
    res = client.patch(
        f"/admin/table/tasks/{created['id']}",
        json={"depends_on_task_id": "block_01", "version_index": 2},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["row"]["depends_on_task_id"] == "block_01"
    assert res.json()["row"]["version_index"] == 2

    bad = client.patch(
        f"/admin/table/tasks/{created['id']}",
        json={"parts_json": "not json"},
        headers=headers,
    )
    assert bad.status_code == 400


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
    # The cascaded step is gone too.
    attempts = client.get("/admin/table/session_steps", headers=headers).json()
    assert attempts["total"] == 0

    assert client.delete("/admin/table/tasks/does-not-exist", headers=headers).status_code == 404

    # Session row delete works.
    sessions = client.get("/admin/table/active_sessions", headers=headers).json()
    assert sessions["total"] == 1
    sid = sessions["rows"][0]["session_id"]
    assert client.delete(f"/admin/table/active_sessions/{sid}", headers=headers).status_code == 200
    assert client.get("/admin/table/active_sessions", headers=headers).json()["total"] == 0
