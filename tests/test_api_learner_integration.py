"""End-to-end API integration test: /start -> /submit -> /complete -> /session/open.

Confirms the learner engine runs inside the real FastAPI routes
(fake judge + fake decomposer, isolated DBs, no LLM calls).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import coach.db as db
import backend.auth as auth
from coach.judge import CoachContent, CoachStep, EvaluationResult
from tests.test_learner_bridge import FakeDecomposer


class FakeJudge:
    def evaluate(self, task, answer):
        coach = CoachContent(
            feedback="Looks good.",
            misconception="",
            steps=[CoachStep("Fix", "Do it correctly.", None)],
        )
        result = EvaluationResult(
            task["id"], task["skill"], task["max_score"], task["max_score"], "OK", coach.to_dict()
        )
        return result, coach


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "coach.db")
    monkeypatch.setenv("LEARNING_PARTNER_DB_URL", f"sqlite:///{tmp_path}/learner.db")

    import learner.engine as engine_mod
    from learner.engine import LearnerEngine

    def make_engine(*args, **kwargs):
        kwargs.setdefault("decomposer", FakeDecomposer())
        return LearnerEngine(*args, **kwargs)

    monkeypatch.setattr(engine_mod, "LearnerEngine", make_engine)
    import coach.judge as judge_mod

    monkeypatch.setattr(judge_mod, "LLMJudge", FakeJudge)

    from coach.tasks import create_task as _seed_task

    _seed_task(
        prompt="Integration seed task. Signature: def f():",
        skill="general",
        owner="system",
        difficulty=2,
        max_score=5,
        hints=[],
        source="seed",
        is_public=True,
        task_id="seed_int_01",
    )
    from backend.main import app
    client = TestClient(app)

    user = auth.upsert_google_user("student@example.com", "Student")
    token = auth.create_token(user["id"])
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


class TestApiFlow:
    def test_start_bootstraps_learner(self, client):
        res = client.post("/api/start", json={})
        assert res.status_code == 200
        data = res.json()
        assert data["learner"] is not None
        assert data["learner"]["learner_id"]

    def test_submit_records_learner_update(self, client):
        started = client.post("/api/start", json={}).json()
        task = started["first_task"]
        res = client.post("/api/submit", json={
            "session_id": started["session_id"],
            "task_id": task["id"],
            "answer": "def f(): pass",
            "hints_used": [],
        })
        assert res.status_code == 200
        data = res.json()
        assert data["learner_update"] is not None
        assert data["learner_update"]["learner_id"]

    def test_custom_question_bootstraps_general_skill(self, client):
        from learner.graph import node_id_for
        from learner.types import NodeType

        started = client.post("/api/start", json={
            "initial_question": "Explain what a cache eviction policy is.",
        }).json()
        assert started["learner"]["primary_node_id"] == str(node_id_for(NodeType.SKILL, "General"))

    def test_complete_includes_learner_snapshot(self, client):
        started = client.post("/api/start", json={}).json()
        task = started["first_task"]
        client.post("/api/submit", json={
            "session_id": started["session_id"],
            "task_id": task["id"],
            "answer": "def f(): pass",
            "hints_used": [],
        })
        complete = client.post("/api/complete", json={"session_id": started["session_id"]}).json()
        assert complete["done"] is True
        assert complete["learner"] is not None
        assert isinstance(complete["learner"]["states"], dict)
        assert isinstance(complete["learner"]["frontier_top"], list)
        assert isinstance(complete["learner"]["misconceptions"], list)

    def test_open_session_returns_learner(self, client):
        started = client.post("/api/start", json={}).json()
        opened = client.post("/api/session/open", json={"id": started["session_id"]}).json()
        assert opened["candidate"] == "student@example.com"
        assert opened["current_task"] is not None
        assert opened["learner"] is not None

    def test_guest_start_also_records_learner(self, client):
        import backend.auth as auth_mod

        original = auth_mod.user_from_token
        auth_mod.user_from_token = lambda token: None
        try:
            res = client.post("/api/start", json={})
        finally:
            auth_mod.user_from_token = original
        assert res.status_code == 200
        assert res.json()["learner"] is not None