"""Collaboration feature: trajectory sharing + Copy-on-Write resume + redo.

Verifies the anonymous share/resume flow: A shares a prefix, B resumes it as a
brand-new episode with B's own beliefs, nothing is cloned until B's first write
(CoW), and the two candidates' data stays fully independent.
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
    from coach.tasks import create_task as _seed_task

    _seed_task(
        prompt="Implement overfitting detection from loss curves. Signature: def detect_overfitting(train_losses, val_losses):",
        owner="system",
        difficulty=2,
        max_score=5,
        source="seed",
        is_public=True,
        tags={"primary": "experiment_design"},
        task_id="seed_ml_01",
    )
    _seed_task(
        prompt="Implement top-k gradient compression. Signature: def topk_compress(grads, k):",
        owner="system",
        difficulty=2,
        max_score=5,
        source="seed",
        is_public=True,
        tags={"primary": "collectives_and_overlap"},
        task_id="seed_sys_01",
    )
    from backend.main import app

    return TestClient(app)


def _start(client, headers=None):
    # Include two tasks so the picker never needs LLM challenge generation.
    res = client.post(
        "/api/v1/sessions",
        json={"task_ids": ["seed_ml_01", "seed_sys_01"]},
        headers=headers or {},
    )
    assert res.status_code == 201
    return res.json()["data"]


def _answer(client, session_id, task_id, answer="def f(): pass", headers=None):
    res = client.post(
        f"/api/v1/sessions/{session_id}/answers",
        json={"task_id": task_id, "answer": answer},
        headers=headers or {},
    )
    assert res.status_code == 200
    return res.json()["data"]


def _share(client, session_id, headers=None, **body):
    res = client.post(
        f"/api/v1/sessions/{session_id}/share", json=body or {}, headers=headers or {}
    )
    assert res.status_code == 200
    return res.json()["data"]


def test_share_is_anonymous_and_strips_answers(client):
    a_headers = {"X-Guest-Id": "sharer-guest-0001"}
    b_headers = {"X-Guest-Id": "resumer-guest-0002"}
    started = _start(client, headers=a_headers)
    task = started["current_task"]
    _answer(client, started["id"], task["id"], answer="alice secret code", headers=a_headers)

    share = _share(client, started["id"], headers=a_headers)
    assert share["token"] and share["url"]
    assert share["step_index"] == 1

    opened = client.get(f"/api/v1/shared/{share['token']}", headers=b_headers).json()["data"]
    assert len(opened["steps"]) == 1
    step = opened["steps"][0]
    assert step["prompt"]  # the shared task prompt is present
    assert step["result"]["score"] == 5
    # No identity, no answers shared.
    assert "candidate" not in opened
    assert "alice secret code" not in step.get("user_answer", "")
    assert step["user_answer"] == ""


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"X-Guest-Id": "sharer-guest-0001", "Origin": "http://localhost:5173"}, "http://localhost:5173/shared/"),
        ({"X-Guest-Id": "sharer-guest-0001"}, "/shared/"),
    ],
)
def test_share_url_is_absolute_from_origin_else_relative(client, monkeypatch, headers, expected):
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    started = _start(client, headers=headers)
    task = started["current_task"]
    _answer(client, started["id"], task["id"], headers=headers)

    share = _share(client, started["id"], headers=headers)
    assert share["url"].startswith(expected)
    assert share["token"] in share["url"]


def test_resume_is_copy_on_write_and_keeps_candidates_isolated(client):
    a_headers = {"X-Guest-Id": "sharer-guest-0001"}
    b_headers = {"X-Guest-Id": "resumer-guest-0002"}

    a_started = _start(client, headers=a_headers)
    a_task = a_started["current_task"]
    _answer(client, a_started["id"], a_task["id"], headers=a_headers)
    share = _share(client, a_started["id"], headers=a_headers)

    # B resumes as a brand-new session, with zero cloned steps yet (CoW).
    resumed = client.post(
        f"/api/v1/shared/{share['token']}/resume", json={}, headers=b_headers
    ).json()["data"]
    assert resumed["candidate"] == "guest-resumer-guest-0002"
    assert resumed["task_index"] == 1
    assert len(resumed["results"]) == 1
    assert resumed["current_task"] is not None

    from coach.steps import count_steps, list_steps

    assert count_steps(resumed["id"]) == 0, "CoW: nothing cloned before first write"
    steps = list_steps(resumed["id"])
    assert steps == []

    # Review shows the prefix as history from the snapshot.
    got = client.get(f"/api/v1/sessions/{resumed['id']}", headers=b_headers).json()["data"]
    assert len(got["results"]) == 1

    # B's first submit forks the prefix into inherited rows + B's own step.
    next_task = resumed["current_task"]
    _answer(client, resumed["id"], next_task["id"], headers=b_headers)
    steps = list_steps(resumed["id"])
    assert len(steps) == 2
    assert steps[0]["inherited"] is True
    assert steps[1]["inherited"] is False

    # A is untouched: A's session still has exactly one own step.
    a_steps = list_steps(a_started["id"])
    assert len(a_steps) == 1
    assert a_steps[0]["inherited"] is False


def test_resume_uses_resumers_own_beliefs(client):
    a_headers = {"X-Guest-Id": "sharer-guest-0001"}
    b_headers = {"X-Guest-Id": "resumer-guest-0002"}

    a_started = _start(client, headers=a_headers)
    a_task = a_started["current_task"]
    data = _answer(client, a_started["id"], a_task["id"], headers=a_headers)
    share = _share(client, a_started["id"], headers=a_headers)

    resumed = client.post(
        f"/api/v1/shared/{share['token']}/resume", json={}, headers=b_headers
    ).json()["data"]

    from coach.tasks import get_skill_belief

    # B has never answered -> no persisted belief -> fresh prior, not A's mean.
    assert get_skill_belief("guest-resumer-guest-0002") is None
    assert resumed["ability"]["questions_answered"] == 0


def test_redo_forks_at_step_and_truncates(client):
    a_headers = {"X-Guest-Id": "sharer-guest-0001"}
    b_headers = {"X-Guest-Id": "resumer-guest-0002"}

    a_started = _start(client, headers=a_headers)
    first = a_started["current_task"]
    _answer(client, a_started["id"], first["id"], headers=a_headers)
    share = _share(client, a_started["id"], headers=a_headers)

    resumed = client.post(
        f"/api/v1/shared/{share['token']}/resume", json={}, headers=b_headers
    ).json()["data"]

    redo = client.post(
        f"/api/v1/sessions/{resumed['id']}/redo",
        json={"step_index": 0, "answer": "brand new answer"},
        headers=b_headers,
    ).json()["data"]
    assert redo["result"]["task_id"] == first["id"]
    assert redo["ability_update"]["new_score"] is not None

    from coach.steps import list_steps

    steps = list_steps(resumed["id"])
    assert len(steps) == 1
    assert steps[0]["inherited"] is False
    assert steps[0]["user_answer"] == "brand new answer"

    # Forked: no longer CoW.
    got = client.get(f"/api/v1/sessions/{resumed['id']}", headers=b_headers).json()["data"]
    assert got["task_index"] == 1


def test_revoke_share_and_owner_only(client):
    a_headers = {"X-Guest-Id": "sharer-guest-0001"}
    b_headers = {"X-Guest-Id": "resumer-guest-0002"}

    a_started = _start(client, headers=a_headers)
    _answer(client, a_started["id"], a_started["current_task"]["id"], headers=a_headers)
    share = _share(client, a_started["id"], headers=a_headers)

    # Non-owner cannot revoke.
    assert client.delete(f"/api/v1/shared/{share['token']}", headers=b_headers).status_code == 403
    # Owner can.
    assert client.delete(f"/api/v1/shared/{share['token']}", headers=a_headers).status_code == 204
    assert client.get(f"/api/v1/shared/{share['token']}", headers=a_headers).status_code == 404


def test_legacy_backfill_reconstructs_steps(tmp_path, monkeypatch):
    """Legacy session_json/feedback_json blobs replay into session_steps."""
    import json

    import coach.db as db
    from coach.session import Session, SkillState

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "legacy.db")
    from coach.db import sqlite_conn

    with sqlite_conn() as conn:
        conn.execute("ALTER TABLE active_sessions ADD COLUMN feedback_json TEXT DEFAULT '[]'")

    sess = Session(
        "guest-legacy-0001",
        tasks=[{"id": "seed_ml_01", "prompt": "Q", "difficulty": 2, "max_score": 5,
                "hints": [], "tags": {"primary": "testing", "secondary": []}}],
    )
    sess.asked_task_ids.add("seed_ml_01")
    sess.index = 1
    sess.ability = SkillState(score=0.62, variance=0.09, questions_answered=1,
                              evidence=["Perfect."])
    full = sess.to_dict()
    full["results"] = [
        {"task_id": "seed_ml_01", "score": 5.0, "max_score": 5.0, "rationale": "Perfect.",
         "coach": {"feedback": "Great", "misconception": "none", "steps": []}}
    ]
    fb = [{"task_id": "seed_ml_01", "prompt": "Q", "user_answer": "def f(): pass",
           "result": {"score": 5.0, "max_score": 5.0}, "feedback": "Great",
           "coach": {"feedback": "Great"}, "hints_used": [],
           "tags": {"primary": "testing", "secondary": []}, "scored": True}]
    with sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO active_sessions (session_id, candidate, session_json, feedback_json, updated_at) "
            "VALUES (?,?,?,?,?)",
            ("legacy1", "guest-legacy-0001", json.dumps(full), json.dumps(fb), "2026-01-01T00:00:00"),
        )

    from coach.steps import backfill_session_steps, list_steps

    backfill_session_steps()
    steps = list_steps("legacy1")
    assert len(steps) == 1
    assert steps[0]["reward"] == 1.0
    assert steps[0]["state_before"]["global"]["questions_answered"] == 0
    assert steps[0]["state_after"]["global"]["questions_answered"] == 1
    assert steps[0]["user_answer"] == "def f(): pass"

    # Idempotent: a second run does not duplicate steps.
    backfill_session_steps()
    assert len(list_steps("legacy1")) == 1