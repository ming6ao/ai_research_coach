"""DB task bank: creation/visibility, solvability ladder, consolidation."""

from __future__ import annotations

import coach.db as db
from coach.solvability import p_solve, tune_difficulty_for_target


def _task(i, difficulty=2):
    return {
        "id": f"t{i}",
        "difficulty": difficulty,
        "prompt": f"Prompt {i}",
        "max_score": 5,
        "hints": [],
    }


def test_create_and_list_tasks_endpoint():
    import coach.judge as judge_mod
    from fastapi.testclient import TestClient

    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    db.DB_PATH = tmp
    judge_mod.LLMJudge = type(
        "J",
        (),
        {"evaluate": lambda self, task, ans, previous_code=None: (__import__("coach.judge").EvaluationResult(task["id"], 5, 5, "ok", {"feedback": "f", "steps": []}), __import__("coach.judge").CoachContent(feedback="f", steps=[]))},
    )
    from backend.main import app

    client = TestClient(app)
    res = client.post("/api/v1/tasks", json={
        "parts": [{"key": "solution", "prompt": "My own question?",
                   "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2,
                   "scaffold": "def solution():\n    # TODO\n    pass\n"}],
        "tags": {"primary": "testing", "secondary": []},
    })
    assert res.status_code == 201
    task = res.json()["data"]
    assert task["prompt"] == "My own question?"
    assert "skill" not in task

    listed = client.get("/api/v1/tasks?page_size=100").json()["data"]
    assert any(t["id"] == task["id"] for t in listed)

    got = client.get(f"/api/v1/tasks/{task['id']}").json()["data"]
    assert got["prompt"] == "My own question?"


def test_private_by_default_shared_when_public(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "p.db")
    from coach.tasks import create_task, list_visible_tasks, single_part

    own = create_task(owner="a@x.com", is_public=False, tags={"primary": "testing"},
                      parts=[single_part("private q", tags={"primary": "testing"},
                                         scaffold="def private_q():\n    # TODO\n    pass\n")])
    pub = create_task(owner="b@x.com", is_public=True, tags={"primary": "caching"},
                      parts=[single_part("public q", tags={"primary": "caching"},
                                         scaffold="def public_q():\n    # TODO\n    pass\n")])
    assert any(t["id"] == own["id"] for t in list_visible_tasks("a@x.com"))
    assert not any(t["id"] == own["id"] for t in list_visible_tasks("b@x.com"))
    assert any(t["id"] == pub["id"] for t in list_visible_tasks("a@x.com"))


def test_generated_tasks_excluded_from_bank(tmp_path, monkeypatch):
    """Generated drills/challenges are session artifacts, never bank tasks."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "gen.db")
    from coach.tasks import create_task, list_visible_tasks, single_part

    bank = create_task(
        owner="a@x.com", is_public=True, tags={"primary": "testing"},
        parts=[single_part("bank q", tags={"primary": "testing"},
                           scaffold="def bank_q():\n    # TODO\n    pass\n")],
    )
    generated = create_task(
        owner="a@x.com", source="generated", is_public=False,
        tags={"primary": "ablations"},
        parts=[single_part("generated q", tags={"primary": "ablations"},
                           scaffold="def generated_q():\n    # TODO\n    pass\n")],
    )
    visible = list_visible_tasks("a@x.com")
    assert any(t["id"] == bank["id"] for t in visible)
    assert not any(t["id"] == generated["id"] for t in visible)


def test_solvability_ladder_targets_80pct():
    # Higher ability -> higher P(solve); harder task -> lower P(solve).
    assert p_solve(0.9, 0.8, 0.1, 1) > p_solve(0.3, 0.3, 0.8, 5)
    d = tune_difficulty_for_target(0.8, 0.7, 0.3, base_difficulty=4)
    assert 1 <= d <= 4
    assert p_solve(0.8, 0.7, 0.3, d) >= 0.7


def test_followup_fires_after_weak_answer_with_gap():
    from coach.remediation import plan_followup
    from coach.session import Session

    session = Session("c", tasks=[_task(0, 3)])
    task = session.tasks[0]
    result = type("R", (), {"score": 1, "max_score": 5})()
    coach = type("C", (), {"feedback": "confused X with Y"})()
    gen = plan_followup(session, task, result, coach)
    # No API key in tests -> deterministic fallback follow-up.
    assert gen is None or gen["difficulty"] <= task["difficulty"]


def test_followup_skipped_on_clean_solve():
    from coach.remediation import plan_followup
    from coach.session import Session

    session = Session("c2", tasks=[_task(0, 3)])
    task = session.tasks[0]
    result = type("R", (), {"score": 5, "max_score": 5})()
    coach = type("C", (), {"feedback": ""})()
    assert plan_followup(session, task, result, coach) is None


def test_context_notes_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ctx.db")
    from coach.tasks import create_task, get_task, update_task

    task = create_task(
        owner="a@x.com",
        parts=[{"key": "solution", "prompt": "Explain caching.",
                "tags": {"primary": "caching"}, "max_score": 5, "difficulty": 2,
                "scaffold": "def solution():\n    # TODO\n    pass\n"}],
        context_notes="Eviction is a prerequisite of caching, often confused with invalidation.",
        tags={"primary": "caching"},
    )
    assert task["context_notes"].startswith("Eviction")
    assert get_task(task["id"])["context_notes"] == task["context_notes"]

    updated = update_task(task["id"], context_notes="New notes.")
    assert updated["context_notes"] == "New notes."


def test_create_schema_wraps_legacy_partless_task(tmp_path, monkeypatch):
    """A legacy partless row becomes a one-part task; the prompt/scaffold columns go."""
    import json

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "legacy.db")
    from coach.db import create_schema, sqlite_conn
    from coach.tasks import get_task

    create_schema()
    # Recreate the retired schema: a task-level prompt + scaffold with no steps.
    with sqlite_conn() as conn:
        conn.execute("ALTER TABLE tasks ADD COLUMN prompt TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE tasks ADD COLUMN scaffold TEXT")
        conn.execute(
            "INSERT INTO tasks (id, owner, scaffold, difficulty, max_score, source, "
            "is_public, created_at, context_notes, tags_json, task_type, parts_json, "
            "language, languages_json, delivery, prompt) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy", "b@x.com", "def solution():\n    # TODO\n    pass\n", 3, 7, "user",
                1, "2024-01-01T00:00:00", "",
                json.dumps({"primary": "testing", "secondary": []}), "implement",
                "[]", "python", '["python"]', "block", "Explain caching.",
            ),
        )
        conn.commit()

    # Force create_schema() to run again for this DB.
    db._schema_done.discard(f"orm:{db.learner_db_url()}")
    create_schema()

    task = get_task("legacy")
    assert task["prompt"] == "Explain caching."
    assert [p["key"] for p in task["parts"]] == ["solution"]
    assert task["parts"][0]["prompt"] == "Explain caching."
    # The legacy task-level scaffold moved onto the step.
    assert "def solution" in task["parts"][0]["scaffold"]
    with sqlite_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    assert "prompt" not in cols
    assert "scaffold" not in cols
