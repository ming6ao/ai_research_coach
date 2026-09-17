"""End-to-end coaching flow test with a fake judge (via the v1 API).

Verifies that per-part scoring updates beliefs and that answers return the
coaching + next task in a {data} envelope, and that completion returns the
progress snapshot.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import coach.db as db
from coach.judge import EvaluationResult, CoachContent, CoachStep


class FakeJudge:
    """Judge that always awards full marks with a canned rationale."""

    def evaluate(self, task, answer, previous_code=None):
        from coach.judge import score_targets

        targets = score_targets(task)
        parts = [
            {"key": p["key"], "score": float(p["max_score"]), "rationale": "Perfect part."}
            for p in targets
        ]
        max_score = sum(int(p["max_score"]) for p in targets)
        coach = CoachContent(
            feedback="Great job!",
            misconception="You had no misconception; the solution is sound.",
            steps=[CoachStep("Confirm the approach", "The implementation is correct.", None)],
        )
        result = EvaluationResult(
            task["id"], max_score, max_score, "Perfect.", coach.to_dict(), parts
        )
        return result, coach


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    import coach.judge as judge_mod

    monkeypatch.setattr(judge_mod, "LLMJudge", FakeJudge)
    # Hermetic categorization: never call the LLM from tests.
    from coach.task_decomposer import TaskDecomposer

    monkeypatch.setattr(
        TaskDecomposer,
        "describe_and_categorize",
        lambda self, prompt: {
            "context_notes": "Auto-generated notes.",
            "tags": {"primary": "caching", "secondary": []},
        },
    )
    from coach.tasks import create_task as _seed_task

    _seed_task(
        prompt="Implement overfitting detection from loss curves. Signature: def detect_overfitting(train_losses, val_losses):",
        owner="bank@example.com",
        difficulty=2,
        max_score=5,
        source="user",
        is_public=True,
        tags={"primary": "experiment_design"},
        task_id="seed_ml_01",
    )
    _seed_task(
        prompt="Implement top-k gradient compression. Signature: def topk_compress(grads, k):",
        owner="bank@example.com",
        difficulty=2,
        max_score=5,
        source="user",
        is_public=True,
        tags={"primary": "collectives_and_overlap"},
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


def _answer(client, session_id, task_id, answer="def f(): pass", headers=None):
    res = client.post(
        f"/api/v1/sessions/{session_id}/answers",
        json={"task_id": task_id, "answer": answer},
        headers=headers or {},
    )
    assert res.status_code == 200
    return res.json()["data"]


def test_step_by_step_updates_per_part_beliefs(client):
    """A two-step task is scored one step at a time; each step updates its tag."""
    from coach.tasks import create_task as _create

    _create(
        prompt="Implement a two-step task.",
        owner="bank@example.com",
        source="user",
        is_public=True,
        parts=[
            {"key": "mean", "prompt": "def mean(xs): ...", "tags": {"primary": "linear_algebra"},
             "max_score": 5, "difficulty": 2},
            {"key": "variance", "prompt": "def variance(xs): ...", "tags": {"primary": "probability_statistics"},
             "max_score": 5, "difficulty": 2},
        ],
        task_id="seed_block_01",
    )
    started = _start(client, task_ids=["seed_block_01"])
    task = started["current_task"]
    assert "hints" not in task
    assert len(task["parts"]) == 1
    assert task["parts"][0]["key"] == "mean"
    assert task["phase_index"] == 1
    assert task["phase_total"] == 2
    assert task["max_score"] == 5

    first = _answer(client, started["id"], task["id"])
    assert first["result"]["score"] == 5
    assert len(first["result"]["parts"]) == 1
    assert first["result"]["parts"][0]["key"] == "mean"
    assert first["ability_update"] is not None

    second = _answer(client, started["id"], "seed_block_01")
    assert second["result"]["parts"][0]["key"] == "variance"

    from coach.tasks import get_area_beliefs

    candidate = started["candidate"]
    beliefs = get_area_beliefs(candidate)
    assert ("skill", "linear_algebra") in beliefs
    assert ("skill", "probability_statistics") in beliefs
    assert beliefs[("skill", "linear_algebra")]["questions_answered"] == 1
    assert beliefs[("skill", "probability_statistics")]["questions_answered"] == 1


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
    """POST /sessions {node} seeds with a random question in that area."""
    from coach.taxonomy import area_of

    res = client.post("/api/v1/sessions", json={"node": "research_method"})
    assert res.status_code == 201
    task = res.json()["data"]["current_task"]
    assert task is not None
    primary = (task["tags"] or {}).get("primary")
    assert area_of(primary) == "research_method"


def test_start_session_with_unknown_family_rejected(client):
    res = client.post("/api/v1/sessions", json={"node": "not_a_family"})
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
    assert "domains" in data["mastery"]
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
