"""Phased task delivery: one phase at a time, pass gate, code carry-forward.

A ``delivery='phased'`` task exposes only its active part; a passing score (or
the attempt cap) advances to the next phase with the candidate's prior code
carried forward. ``delivery='block'`` is unchanged.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import coach.db as db
from coach.judge import CoachContent, EvaluationResult


class ScriptedJudge:
    """Judge that awards the next scripted score to every target part."""

    def __init__(self):
        self.scores: list[float] = []

    def evaluate(self, task, answer, previous_code=None):
        from coach.judge import score_targets

        targets = score_targets(task)
        score = float(self.scores.pop(0)) if self.scores else 0.0
        parts = []
        total = 0.0
        for p in targets:
            s = min(score, float(p["max_score"]))
            total += s
            parts.append({"key": p["key"], "score": s, "rationale": "r"})
        max_score = sum(int(p["max_score"]) for p in targets)
        coach = CoachContent(feedback="", misconception="", steps=[])
        return (
            EvaluationResult(task["id"], total, max_score, "r", coach.to_dict(), parts),
            coach,
        )


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "phased.db")
    import coach.judge as judge_mod

    judge = ScriptedJudge()
    monkeypatch.setattr(judge_mod, "LLMJudge", lambda: judge)
    from coach.tasks import create_task

    create_task(
        prompt="Two-phase block.",
        owner="system",
        source="seed",
        is_public=True,
        task_id="phased_01",
        delivery="phased",
        parts=[
            {"key": "p1", "prompt": "Implement def p1(x): ...",
             "tags": {"primary": "vision_encoders"}, "max_score": 5, "difficulty": 2,
              "scaffold": "def p1(x):\n    pass\n"},
            {"key": "p2", "prompt": "Implement def p2(y): ...",
             "tags": {"primary": "state_space_models"}, "max_score": 5, "difficulty": 3,
             "scaffold": "def p2(y):\n    pass\n"},
        ],
    )
    create_task(
        prompt="Plain task. Signature: def plain(x):",
        owner="system",
        source="seed",
        is_public=True,
        task_id="plain_01",
        max_score=5,
        difficulty=2,
        tags={"primary": "testing"},
    )
    from backend.main import app

    return TestClient(app), judge


def _start(client, task_ids):
    res = client.post("/api/v1/sessions", json={"task_ids": task_ids})
    assert res.status_code == 201
    return res.json()["data"]


def _answer(client, session_id, task_id, answer):
    res = client.post(
        f"/api/v1/sessions/{session_id}/answers",
        json={"task_id": task_id, "answer": answer},
    )
    assert res.status_code == 200
    return res.json()["data"]


def test_phase_view_and_pass_advance(ctx):
    client, judge = ctx
    data = _start(client, ["phased_01"])
    task = data["current_task"]
    assert task["delivery"] == "phased"
    assert task["phase_index"] == 1 and task["phase_total"] == 2
    assert [p["key"] for p in task["parts"]] == ["p1"]
    assert "def p1" in task["scaffold"]

    judge.scores = [5]
    r = _answer(client, data["id"], "phased_01", "PHASE1 CODE")
    assert r["already_answered"] is False
    assert r["result"]["parts"][0]["key"] == "p1"
    nxt = r["next_task"]
    assert nxt["id"] == "phased_01"
    assert nxt["phase_index"] == 2
    assert [p["key"] for p in nxt["parts"]] == ["p2"]
    assert nxt["previous_code"] == "PHASE1 CODE"
    assert "def p2" in nxt["scaffold"]


def test_failed_phase_retries_then_cap_advances(ctx):
    client, judge = ctx
    data = _start(client, ["phased_01"])

    judge.scores = [0, 0]
    first = _answer(client, data["id"], "phased_01", "TRY1")
    assert first["next_task"]["id"] == "phased_01"
    assert first["next_task"]["phase_index"] == 1  # same phase retried
    second = _answer(client, data["id"], "phased_01", "TRY2")
    assert second["next_task"]["phase_index"] == 1

    # Third failure hits PHASE_MAX_ATTEMPTS (default 3) and advances anyway.
    judge.scores = [0]
    third = _answer(client, data["id"], "phased_01", "TRY3")
    assert third["next_task"]["phase_index"] == 2


def test_failed_phase_replay_is_idempotent(ctx):
    client, judge = ctx
    data = _start(client, ["phased_01"])
    judge.scores = [0]
    _answer(client, data["id"], "phased_01", "SAME")
    replay = _answer(client, data["id"], "phased_01", "SAME")
    assert replay["already_answered"] is True
    assert replay["result"]["parts"][0]["key"] == "p1"


def test_resume_mid_phases(ctx):
    client, judge = ctx
    data = _start(client, ["phased_01"])
    judge.scores = [5]
    _answer(client, data["id"], "phased_01", "PHASE1 CODE")

    resume = client.get(f"/api/v1/sessions/{data['id']}").json()["data"]
    assert resume["current_task"]["id"] == "phased_01"
    assert resume["current_task"]["phase_index"] == 2
    assert resume["current_task"]["previous_code"] == "PHASE1 CODE"


def test_completed_phased_task_moves_to_bank(ctx):
    client, judge = ctx
    data = _start(client, ["phased_01", "plain_01"])
    judge.scores = [5, 5]
    _answer(client, data["id"], "phased_01", "PHASE1 CODE")
    done = _answer(client, data["id"], "phased_01", "PHASE2 CODE")
    assert done["next_task"]["id"] == "plain_01"


def test_block_delivery_scores_all_parts_in_one_submission(ctx, monkeypatch):
    client, judge = ctx
    from coach.tasks import create_task

    create_task(
        prompt="Two-part block.",
        owner="system",
        source="seed",
        is_public=True,
        task_id="block_01",
        parts=[
            {"key": "a", "prompt": "def a(): ...", "tags": {"primary": "vision_encoders"},
             "max_score": 5, "difficulty": 2},
            {"key": "b", "prompt": "def b(): ...", "tags": {"primary": "state_space_models"},
             "max_score": 5, "difficulty": 3},
        ],
    )
    data = _start(client, ["block_01"])
    assert data["current_task"].get("delivery") in (None, "block")
    assert len(data["current_task"]["parts"]) == 2

    judge.scores = [5]
    r = _answer(client, data["id"], "block_01", "BOTH")
    keys = sorted(p["key"] for p in r["result"]["parts"])
    assert keys == ["a", "b"]
