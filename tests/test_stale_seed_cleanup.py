"""Stale seed-bank cleanup: preview + delete cascade (admin-only)."""

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


def _seed_stale_rows():
    """Insert legacy/pre-catalog rows + a dependent child + a session."""
    create_task(
        prompt="Legacy scaling task",
        owner="system",
        source="seed",
        is_public=True,
        task_id="mr_rc_scaling",
    )
    create_task(
        prompt="Legacy softmax task",
        owner="system",
        source="seed",
        is_public=True,
        task_id="mr_rc_softmax",
    )
    create_task(
        prompt="Duplicate oversample task",
        owner="system",
        source="seed",
        is_public=True,
        task_id="seed_seed_oversample",
    )
    create_task(
        prompt="Drill on scaling",
        owner="system",
        source="generated",
        is_public=False,
        task_id="remed_child",
        parent_task_id="mr_rc_scaling",
    )
    with db.sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO active_sessions (session_id, candidate, session_json, status, updated_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            (
                "sess_stale",
                "guest-abc",
                '{"session": {"candidate": "guest-abc"}, "current_task_id": "mr_rc_scaling"}',
                "2026-01-01 00:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO active_sessions (session_id, candidate, session_json, status, updated_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            (
                "sess_clean",
                "guest-xyz",
                '{"session": {"candidate": "guest-xyz"}, "current_task_id": "seed_transformer_decode"}',
                "2026-01-01 00:00:00",
            ),
        )
        conn.commit()


def test_stale_seeds_require_admin(client):
    user = _login(NON_ADMIN)
    _seed_stale_rows()
    assert client.get("/admin/stale-seeds/preview", headers=_h(user)).status_code == 403
    assert client.delete("/admin/stale-seeds", headers=_h(user)).status_code == 403
    assert client.get("/admin/stale-seeds/preview").status_code == 401


def test_stale_seeds_preview_is_dry_run(client):
    admin = _login(ADMIN)
    _seed_stale_rows()
    res = client.get("/admin/stale-seeds/preview", headers=_h(admin))
    assert res.status_code == 200
    data = res.json()
    assert data["preview"] is True
    assert set(data["stale_tasks"]) == {
        "mr_rc_scaling",
        "mr_rc_softmax",
        "seed_seed_oversample",
    }
    assert data["child_tasks"] == ["remed_child"]
    assert data["sessions"] == ["sess_stale"]
    assert data["counts"] == {
        "stale_tasks": 3,
        "child_tasks": 1,
        "sessions": 1,
        "session_steps": 0,
    }

    from coach.admin import stale_seed_cleanup

    with db.sqlite_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM active_sessions").fetchone()[0] == 2


def test_stale_seeds_delete_cascade(client):
    admin = _login(ADMIN)
    _seed_stale_rows()
    res = client.delete("/admin/stale-seeds", headers=_h(admin))
    assert res.status_code == 200
    data = res.json()
    assert data["preview"] is False
    assert data["counts"]["stale_tasks"] == 3
    assert data["counts"]["child_tasks"] == 1
    assert data["counts"]["sessions"] == 1

    with db.sqlite_conn() as conn:
        remaining_sessions = conn.execute(
            "SELECT session_id FROM active_sessions ORDER BY session_id"
        ).fetchall()
    assert [r[0] for r in remaining_sessions] == ["sess_clean"]

    from coach.tasks import get_task

    for tid in ("mr_rc_scaling", "mr_rc_softmax", "seed_seed_oversample", "remed_child"):
        assert get_task(tid) is None
    assert get_task("seed_transformer_decode") is not None


def test_stale_seeds_delete_is_idempotent(client):
    admin = _login(ADMIN)
    _seed_stale_rows()
    client.delete("/admin/stale-seeds", headers=_h(admin))
    res = client.delete("/admin/stale-seeds", headers=_h(admin))
    assert res.status_code == 200
    data = res.json()
    assert data["counts"] == {
        "stale_tasks": 0,
        "child_tasks": 0,
        "sessions": 0,
        "session_steps": 0,
    }


def test_guest_data_requires_admin(client):
    user = _login(NON_ADMIN)
    assert client.get("/admin/guest-data/preview", headers=_h(user)).status_code == 403
    assert client.delete("/admin/guest-data", headers=_h(user)).status_code == 403
    assert client.get("/admin/guest-data/preview").status_code == 401


def test_guest_data_delete_keeps_signed_in_user(client):
    admin = _login(ADMIN)
    create_task(
        prompt="Guest-owned task",
        owner="guest-abc",
        source="user",
        is_public=False,
        task_id="guest_task",
    )
    create_task(
        prompt="Signed-in owned task",
        owner=ADMIN,
        source="user",
        is_public=False,
        task_id="owner_task",
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