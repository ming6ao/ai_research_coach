"""End-to-end coaching flow test with a fake judge (via the v1 API).

Verifies that viewing hints reduces the effective mastery for a task even when
the submitted code is perfect, that answers return the coaching + next task in
a {data} envelope, and that completion returns the progress snapshot.
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
            task["id"], max_score, max_score, "Perfect.", coach.to_dict()
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


def _start(client, initial_question=None, task_ids=None, headers=None):
    body = {}
    if initial_question:
        body["initial_question"] = initial_question
    if task_ids:
        body["task_ids"] = task_ids
    res = client.post("/api/v1/sessions", json=body, headers=headers or {})
    assert res.status_code == 201
    data = res.json()["data"]
    assert "mode" not in data
    return data


def _answer(client, session_id, task_id, answer="def f(): pass", hints_used=None, headers=None):
    res = client.post(
        f"/api/v1/sessions/{session_id}/answers",
        json={"task_id": task_id, "answer": answer, "hints_used": hints_used or []},
        headers=headers or {},
    )
    assert res.status_code == 200
    return res.json()["data"]


def test_hints_reduce_mastery_for_perfect_code(client):
    no_hints = _start(client, task_ids=["seed_ml_01"])
    task = no_hints["current_task"]
    assert task is not None
    assert task["hints"], "task should carry hints"

    data = _answer(client, no_hints["id"], task["id"])
    score_without_hints = data["ability_update"]["new_score"]

    with_hints = _start(client, task_ids=["seed_ml_01"])
    task2 = with_hints["current_task"]
    all_hint_ids = [h["id"] for h in task2["hints"]]
    data2 = _answer(client, with_hints["id"], task2["id"], hints_used=all_hint_ids)
    score_with_hints = data2["ability_update"]["new_score"]

    assert score_with_hints < score_without_hints


def test_submit_returns_coaching_and_next_task(client):
    started = _start(client)
    task = started["current_task"]
    data = _answer(client, started["id"], task["id"])
    assert data["coach"]["misconception"], "coach should identify a gap/misconception"
    assert data["coach"]["steps"], "coach should provide step-by-step guidance"
    assert data["coach"]["steps"][0]["title"]
    assert "next_task" in data, "the picked task is still returned (gated by the UI)"
    assert data["coach"]["feedback"] == "Great job!"
    assert data["already_answered"] is False
    assert "feedback" not in data, "top-level feedback alias removed in v1"
    assert "learner_update" not in data


def test_complete_returns_progress_snapshot(client):
    started = _start(client)
    task = started["current_task"]
    _answer(client, started["id"], task["id"])
    res = client.post(f"/api/v1/sessions/{started['id']}/completion", json={})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["done"] is True
    assert "ability" in data
    assert "learner" not in data
    assert "verdict" not in data
    assert "overall_score" not in data


def test_custom_question_injected_as_first_task(client):
    started = _start(client, initial_question="Explain what a cache eviction policy is.")
    assert started["current_task"] is not None
    assert started["current_task"]["prompt"] == "Explain what a cache eviction policy is."
    assert started["total_tasks"] > 1


def test_submit_is_idempotent(client):
    started = _start(client)
    task = started["current_task"]
    first = _answer(client, started["id"], task["id"])
    second = _answer(client, started["id"], task["id"])
    assert second["already_answered"] is True
    assert second["ability_update"] is None
    assert second["result"]["task_id"] == first["result"]["task_id"]


def test_get_and_delete_session(client):
    started = _start(client)
    res = client.get(f"/api/v1/sessions/{started['id']}")
    assert res.status_code == 200
    assert res.json()["data"]["id"] == started["id"]

    assert client.get("/api/v1/sessions/does-not-exist").status_code == 404

    assert client.delete(f"/api/v1/sessions/{started['id']}").status_code == 204
    assert client.get(f"/api/v1/sessions/{started['id']}").status_code == 404


def test_start_session_with_family_seed(client):
    """POST /sessions {family} seeds with a random question in that family."""
    from coach.taxonomy import family_of

    res = client.post("/api/v1/sessions", json={"family": "dl_arch"})
    assert res.status_code == 201
    task = res.json()["data"]["current_task"]
    assert task is not None
    primary = (task["tags"] or {}).get("primary")
    assert family_of(primary) == "dl_arch"


def test_start_session_with_unknown_family_rejected(client):
    res = client.post("/api/v1/sessions", json={"family": "not_a_family"})
    assert res.status_code == 422


def test_overview_returns_persisted_progress(client):
    headers = {"X-Guest-Id": "overview-guest-0001"}
    started = _start(client, headers=headers)
    task = started["current_task"]
    _answer(client, started["id"], task["id"], headers=headers)

    res = client.get("/api/v1/me/overview", headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["candidate"] == "guest-overview-guest-0001"
    assert data["ability"] is not None
    assert data["ability"]["questions_answered"] == 1
    assert data["mastery"] is not None
    assert "families" in data["mastery"]
    assert len(data["sessions"]) >= 1
    assert data["sessions"][0]["id"] == started["id"]


def test_guest_id_keeps_candidate_stable(client):
    """A stable X-Guest-Id header gives one persistent guest identity."""
    headers = {"X-Guest-Id": "browser-guest-0001"}
    first = client.post("/api/v1/sessions", json={}, headers=headers)
    assert first.status_code == 201
    task = first.json()["data"]["current_task"]
    _answer(client, first.json()["data"]["id"], task["id"], headers=headers)

    second = client.post("/api/v1/sessions", json={}, headers=headers)
    assert second.status_code == 201

    overview = client.get("/api/v1/me/overview", headers=headers).json()["data"]
    assert overview["candidate"] == "guest-browser-guest-0001"
    assert overview["ability"]["questions_answered"] == 1
    assert len(overview["sessions"]) == 2
