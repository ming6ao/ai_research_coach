"""DB reset tool: wipe app data, preserve auth, re-bootstrap the catalog."""

from __future__ import annotations

from datetime import datetime, timezone

import coach.db as db
from coach.db import reset_database
from coach.seed_bank import SEED_CATALOG, seed_question_bank


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
    create_task(prompt="Custom user task?", owner="alice@example.com")
    with db.sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO active_sessions (session_id, candidate, session_json, status, updated_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            ("s_1", "guest-abc", "{}", now),
        )
        conn.execute(
            "INSERT INTO trajectory_shares (id, source_session_id, step_index, snapshot_json, "
            "created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("share_1", "s_1", 0, "{}", "guest-abc", now),
        )
        conn.commit()
    session = db.learner_session()
    try:
        session.add(
            SessionStepModel(
                id="step_1", session_id="s_1", candidate="guest-abc", step_index=0,
                task_id="seed_transformer_decode", role="bank", reward=0.8, created_at=dt,
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
    seed_question_bank()
    _add_user_and_auth()
    _add_app_data()

    result = reset_database(preview=True)
    assert result["preview"] is True
    assert result["total_deleted"] > 0
    assert result["wiped"]["tasks"] >= len(SEED_CATALOG) + 1  # catalog + 1 custom task
    assert result["wiped"]["active_sessions"] == 1
    assert result["wiped"]["session_steps"] == 1
    assert result["wiped"]["user_skill_beliefs"] == 1
    assert result["wiped"]["trajectory_shares"] == 1
    assert "users" in result["preserved"] and "auth_tokens" in result["preserved"]
    # Preview must not mutate anything.
    with db.sqlite_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] >= len(SEED_CATALOG) + 1


def test_reset_wipes_app_data_keeps_auth_and_resyncs(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "reset.db")
    seed_question_bank()
    _add_user_and_auth()
    _add_app_data()

    result = reset_database(preview=False)
    assert result["preview"] is False
    assert result["total_deleted"] > 0
    assert result["seeded"] == len(SEED_CATALOG)

    with db.sqlite_conn() as conn:
        # Auth/identity is preserved.
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM auth_tokens").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 1
        # App data is gone.
        assert conn.execute("SELECT COUNT(*) FROM active_sessions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM trajectory_shares").fetchone()[0] == 0
        # Only the catalog seeds remain, with parts + version links populated.
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == len(SEED_CATALOG)
        assert conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE source != 'seed'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE parts_json = '[]' AND version_index = 1"
        ).fetchone()[0] == 0

    session = db.learner_session()
    try:
        from coach.steps import SessionStepModel
        from coach.tasks import SkillBeliefModel

        assert session.query(SessionStepModel).count() == 0
        assert session.query(SkillBeliefModel).count() == 0
    finally:
        session.close()

    # Every seed row now matches the catalog exactly.
    for seed in SEED_CATALOG:
        with db.sqlite_conn() as conn:
            row = conn.execute(
                "SELECT version_index, depends_on_task_id, version_root_id "
                "FROM tasks WHERE id = ?",
                (f"seed_{seed['slug']}",),
            ).fetchone()
        assert row is not None, seed["slug"]
        if seed.get("depends_on"):
            assert row[0] == 2
            assert row[1] == f"seed_{seed['depends_on']}"
            assert row[2] == f"seed_{seed['depends_on']}"
        else:
            assert row[0] == 1
            assert row[1] is None
            assert row[2] == f"seed_{seed['slug']}"


def test_catalog_has_no_self_loops_and_resolvable_version_links():
    ids = {f"seed_{s['slug']}" for s in SEED_CATALOG}
    for seed in SEED_CATALOG:
        tid = f"seed_{seed['slug']}"
        depends = seed.get("depends_on")
        if depends is None:
            continue
        pred = f"seed_{depends}"
        assert pred != tid, f"{tid} self-references"
        assert pred in ids, f"{tid} -> missing {pred}"


def test_reset_cli_requires_confirm(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "reset_cli.db")
    from coach.seed_bank import main

    seed_question_bank()
    _add_app_data()
    before = reset_database(preview=True)["total_deleted"]
    assert before > 0

    code = main(["--reset"])
    assert code == 0
    assert "DRY RUN" in capsys.readouterr().out
    # No confirmation -> nothing wiped.
    assert reset_database(preview=True)["total_deleted"] == before

    code = main(["--reset", "--yes"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Reset complete" in out
    # After a full reset only the 30 catalog seeds remain (users/auth kept).
    result = reset_database(preview=True)
    assert result["total_deleted"] == len(SEED_CATALOG)
    assert result["wiped"]["tasks"] == len(SEED_CATALOG)
    assert result["wiped"]["active_sessions"] == 0
    assert result["wiped"]["session_steps"] == 0