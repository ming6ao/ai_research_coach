"""End-to-end coaching flow test with a fake judge (via the FastAPI routes).

Verifies that viewing hints reduces the effective mastery for a task even when
the submitted code is perfect, that /submit returns the coaching + next task,
and that /complete returns the progress snapshot (no report/verdict).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import coach.db as db
from coach.judge import EvaluationResult, CoachContent, CoachStep


class FakeJudge:
    """Judge that always awards full marks with a canned rationale."""

    def evaluate(self, task, answer):
        max_score = task.get("max_score", 5)
        coach = CoachContent(
            feedback="Great job!",
            misconception="You had no misconception; the solution is sound.",
            steps=[CoachStep("Confirm the approach", "The implementation is correct.", None)],
        )
        result = EvaluationResult(
            task["id"], task["skill"], max_score, max_score, "Perfect.", coach.to_dict()
        )
        return result, coach


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    import coach.judge as judge_mod

    monkeypatch.setattr(judge_mod, "LLMJudge", FakeJudge)
    from coach.tasks import create_task as _seed_task

    _seed_task(
        prompt="Implement overfitting detection from loss curves. Signature: def detect_overfitting(train_losses, val_losses):",
        skill="ml_modeling",
        owner="system",
        difficulty=2,
        max_score=5,
        hints=[
            {"id": "h1", "text": "Training loss falls while validation rises.", "weight": 0.05, "reveal_threshold": 0.75},
            {"id": "h2", "text": "Find the first local minimum of val loss.", "weight": 0.08, "reveal_threshold": 0.65},
        ],
        source="seed",
        is_public=True,
        task_id="seed_ml_01",
    )
    _seed_task(
        prompt="Implement top-k gradient compression. Signature: def topk_compress(grads, k):",
        skill="ml_systems",
        owner="system",
        difficulty=2,
        max_score=5,
        hints=[{"id": "h1", "text": "Keep largest magnitudes.", "weight": 0.05, "reveal_threshold": 0.75}],
        source="seed",
        is_public=True,
        task_id="seed_sys_01",
    )
    from backend.main import app

    return TestClient(app)


def _start(client, initial_question=None):
    body = {"initial_question": initial_question} if initial_question else {}
    res = client.post("/api/start", json=body)
    assert res.status_code == 200
    data = res.json()
    assert "mode" not in data
    return data


def test_hints_reduce_mastery_for_perfect_code(client):
    no_hints = _start(client)
    task = no_hints["first_task"]
    assert task is not None
    assert task["hints"], "task should carry hints"

    resp = client.post("/api/submit", json={
        "session_id": no_hints["session_id"],
        "task_id": task["id"],
        "answer": "def f(): pass",
        "hints_used": [],
    })
    assert resp.status_code == 200
    score_without_hints = resp.json()["skill_update"]["new_score"]

    with_hints = _start(client)
    task2 = with_hints["first_task"]
    all_hint_ids = [h["id"] for h in task2["hints"]]
    resp2 = client.post("/api/submit", json={
        "session_id": with_hints["session_id"],
        "task_id": task2["id"],
        "answer": "def f(): pass",
        "hints_used": all_hint_ids,
    })
    assert resp2.status_code == 200
    score_with_hints = resp2.json()["skill_update"]["new_score"]

    assert score_with_hints < score_without_hints


def test_submit_returns_coaching_and_next_task(client):
    started = _start(client)
    task = started["first_task"]
    resp = client.post("/api/submit", json={
        "session_id": started["session_id"],
        "task_id": task["id"],
        "answer": "def f(): pass",
        "hints_used": [],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["coach"]["misconception"], "coach should identify a gap/misconception"
    assert data["coach"]["steps"], "coach should provide step-by-step guidance"
    assert data["coach"]["steps"][0]["title"]
    assert "next_task" in data, "the picked task is still returned (gated by the UI)"
    assert data["feedback"] == "Great job!"
    assert data["learner_update"] is not None
    assert data["learner_update"]["learner_id"]


def test_complete_returns_progress_snapshot(client):
    started = _start(client)
    task = started["first_task"]
    client.post("/api/submit", json={
        "session_id": started["session_id"],
        "task_id": task["id"],
        "answer": "def f(): pass",
        "hints_used": [],
    })
    res = client.post("/api/complete", json={"session_id": started["session_id"]})
    assert res.status_code == 200
    data = res.json()
    assert data["done"] is True
    assert "skill_states" in data
    assert "learner" in data
    assert "verdict" not in data
    assert "overall_score" not in data


def test_custom_question_injected_as_first_task(client):
    started = _start(client, initial_question="Explain what a cache eviction policy is.")
    assert started["first_task"] is not None
    assert started["first_task"]["prompt"] == "Explain what a cache eviction policy is."
    assert started["total_tasks"] > 1


def test_submit_is_idempotent(client):
    started = _start(client)
    task = started["first_task"]
    first = client.post("/api/submit", json={
        "session_id": started["session_id"],
        "task_id": task["id"],
        "answer": "def f(): pass",
        "hints_used": [],
    }).json()
    second = client.post("/api/submit", json={
        "session_id": started["session_id"],
        "task_id": task["id"],
        "answer": "def f(): pass",
        "hints_used": [],
    }).json()
    assert second["note"] == "Already answered."
    assert second["result"]["task_id"] == first["result"]["task_id"]