"""DB reset tool: wipe activity/progress, preserve auth and the task bank."""

from __future__ import annotations

from datetime import datetime, timezone

import coach.db as db
from coach.db import reset_database


def _now() -> str:
    return str(db.naive_utc(datetime.now(timezone.utc)))


def _add_user_and_auth():
    with db.sqlite_conn() as conn:
        now = _now()
        conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("u_1", "alice@example.com", "x", "Alice", now),
        )
        conn.execute(
            "INSERT INTO auth_tokens (token, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            ("tok_1", "u_1", now, now),
        )
        conn.execute(
            "INSERT INTO oauth_states (state, expires_at) VALUES (?, ?)",
            ("state_1", now),
        )
        conn.commit()


def _add_app_data():
    from coach.steps import SessionStepModel
    from coach.tasks import SkillBeliefModel, create_task

    now = _now()
    dt = db.naive_utc(datetime.now(timezone.utc))
    task = create_task(
        owner="alice@example.com", tags={"primary": "testing"},
        parts=[{"key": "solution", "prompt": "Custom user task?",
                "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2,
                "scaffold": "def solution():\n    # TODO: implement\n    pass\n"}],
    )
    with db.sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO active_sessions (session_id, candidate, session_json, status, updated_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            ("s_1", "guest-abc", "{}", now),
        )
        conn.commit()
    session = db.learner_session()
    try:
        session.add(
            SessionStepModel(
                id="step_1", session_id="s_1", candidate="guest-abc", step_index=0,
                task_id=task["id"], role="bank", reward=0.8, created_at=dt,
            )
        )
        session.add(
            SkillBeliefModel(
                id="belief_1", candidate="guest-abc", level="global", key="overall",
                mean=0.6, variance=0.1, questions_answered=1, updated_at=dt,
            )
        )
        session.commit()
    finally:
        session.close()


def test_reset_preview_reports_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "reset_preview.db")
    _add_user_and_auth()
    _add_app_data()

    result = reset_database(preview=True)
    assert result["preview"] is True
    assert result["total_deleted"] > 0
    assert result["wiped"]["active_sessions"] == 1
    assert result["wiped"]["session_steps"] == 1
    assert result["wiped"]["user_skill_beliefs"] == 1
    assert "tasks" not in result["wiped"]  # the task bank is preserved
    assert "users" in result["preserved"] and "auth_tokens" in result["preserved"]
    assert "tasks" in result["preserved"]
    # Preview must not mutate anything.
    with db.sqlite_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_reset_wipes_activity_keeps_auth_and_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "reset.db")
    _add_user_and_auth()
    _add_app_data()

    result = reset_database(preview=False)
    assert result["preview"] is False
    assert result["total_deleted"] > 0

    with db.sqlite_conn() as conn:
        # Auth/identity is preserved.
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM auth_tokens").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 1
        # Activity data is gone.
        assert conn.execute("SELECT COUNT(*) FROM active_sessions").fetchone()[0] == 0
        # The task bank survives the reset (DB is the source of truth).
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1

    session = db.learner_session()
    try:
        from coach.steps import SessionStepModel
        from coach.tasks import SkillBeliefModel

        assert session.query(SessionStepModel).count() == 0
        assert session.query(SkillBeliefModel).count() == 0
    finally:
        session.close()


def test_reset_drops_legacy_generated_tasks(tmp_path, monkeypatch):
    """Legacy generated rows are session artifacts, wiped with the sessions."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "reset_gen.db")
    _add_app_data()
    from coach.tasks import create_task, get_task

    generated = create_task(
        owner="alice@example.com", source="generated", tags={"primary": "ablations"},
        parts=[{"key": "solution", "prompt": "Legacy drill?",
                "tags": {"primary": "ablations"}, "max_score": 5, "difficulty": 2,
                "scaffold": "def solution():\n    # TODO: implement\n    pass\n"}],
    )
    preview = reset_database(preview=True)
    assert preview["wiped"]["generated_tasks"] == 1
    result = reset_database(preview=False)
    assert result["wiped"]["generated_tasks"] == 1
    assert get_task(generated["id"]) is None
    # Authored bank questions survive.
    with db.sqlite_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_reset_keeps_custom_skills_without_wipe_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "reset_custom.db")
    from coach.custom_skills import create_custom_skill, list_custom_skills

    create_custom_skill("custom_metric", "evaluation", "a@x.com")
    reset_database(preview=False)
    assert [s["skill"] for s in list_custom_skills()] == ["custom_metric"]


def test_reset_with_wipe_tasks_drops_custom_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "reset_custom_wipe.db")
    from coach.custom_skills import create_custom_skill, list_custom_skills
    from coach.taxonomy import LEAF_NODES

    create_custom_skill("custom_metric", "evaluation", "a@x.com")
    assert "custom_metric" in LEAF_NODES
    reset_database(preview=False, wipe_tasks=True)
    assert list_custom_skills() == []
    assert "custom_metric" not in LEAF_NODES


def test_reset_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "reset_again.db")
    _add_app_data()

    reset_database(preview=False)
    again = reset_database(preview=False)
    assert again["total_deleted"] == 0
    with db.sqlite_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_reset_with_wipe_tasks_clears_task_bank(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "reset_tasks.db")
    _add_user_and_auth()
    _add_app_data()

    preview = reset_database(preview=True, wipe_tasks=True)
    assert preview["wipe_tasks"] is True
    assert "tasks" in preview["wiped"]
    assert "tasks" not in preview["preserved"]

    result = reset_database(preview=False, wipe_tasks=True)
    assert result["wiped"]["tasks"] == 1
    with db.sqlite_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
        # Identity/auth is still preserved.
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1