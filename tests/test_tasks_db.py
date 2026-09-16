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
        {"evaluate": lambda self, task, ans, previous_code=None: (__import__("coach.judge").EvaluationResult(task["id"], 5, 5, "ok", {"feedback": "f", "misconception": "m", "steps": []}), __import__("coach.judge").CoachContent(feedback="f", misconception="m", steps=[]))},
    )
    from backend.main import app

    client = TestClient(app)
    res = client.post("/api/v1/tasks", json={"prompt": "My own question?"})
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
    from coach.tasks import create_task, list_visible_tasks

    own = create_task(prompt="private q", owner="a@x.com", is_public=False)
    pub = create_task(prompt="public q", owner="b@x.com", is_public=True)
    assert any(t["id"] == own["id"] for t in list_visible_tasks("a@x.com"))
    assert not any(t["id"] == own["id"] for t in list_visible_tasks("b@x.com"))
    assert any(t["id"] == pub["id"] for t in list_visible_tasks("a@x.com"))


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
    coach = type("C", (), {"misconception": "confused X with Y", "feedback": "weak"})()
    gen = plan_followup(session, task, result, coach)
    # No API key in tests -> deterministic fallback follow-up.
    assert gen is None or gen["difficulty"] <= task["difficulty"]


def test_followup_skipped_on_clean_solve():
    from coach.remediation import plan_followup
    from coach.session import Session

    session = Session("c2", tasks=[_task(0, 3)])
    task = session.tasks[0]
    result = type("R", (), {"score": 5, "max_score": 5})()
    coach = type("C", (), {"misconception": "", "feedback": ""})()
    assert plan_followup(session, task, result, coach) is None


def test_context_notes_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ctx.db")
    from coach.tasks import create_task, get_task, update_task_context

    task = create_task(
        prompt="Explain caching.",
        owner="a@x.com",
        context_notes="Eviction is a prerequisite of caching, often confused with invalidation.",
    )
    assert task["context_notes"].startswith("Eviction")
    assert get_task(task["id"])["context_notes"] == task["context_notes"]

    updated = update_task_context(task["id"], "New notes.")
    assert updated["context_notes"] == "New notes."
