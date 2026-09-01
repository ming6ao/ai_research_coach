"""End-to-end API integration test: /start -> /submit -> /report.

Confirms the learning-partner bridge runs inside the real FastAPI routes
(fake judge + fake decomposer, isolated DBs, no LLM calls).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import backend.dependencies as deps
import core.storage as storage
from evaluators.base import CoachContent, CoachStep, EvaluationResult
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
    db = tmp_path / "coach.db"
    monkeypatch.setattr(auth, "DB_PATH", db)
    monkeypatch.setattr(deps, "DB_PATH", db)
    monkeypatch.setattr(storage, "DB_PATH", db)
    monkeypatch.setenv("LEARNING_PARTNER_DB_URL", f"sqlite:///{tmp_path}/learner.db")

    import core.learner_bridge as bridge_mod
    from core.learner_bridge import LearnerBridge

    monkeypatch.setattr(bridge_mod, "LearnerBridge", lambda: LearnerBridge(
        db_url=f"sqlite:///{tmp_path}/learner.db", decomposer=FakeDecomposer()
    ))
    from backend.main import app
    client = TestClient(app)

    # Real authenticated session (assessment mode) so /report is reachable.
    user = auth.upsert_google_user("student@example.com", "Student")
    token = auth.create_token(user["id"])
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


class TestApiFlow:
    def test_start_bootstraps_learner(self, client):
        res = client.post("/api/start", json={"candidate_name": "student@example.com"})
        assert res.status_code == 200
        data = res.json()
        assert data["learner"] is not None
        assert data["learner"]["learner_id"]

    def test_submit_records_learner_update(self, client, monkeypatch):
        import evaluators.judge as judge_mod

        monkeypatch.setattr(judge_mod, "LLMJudge", FakeJudge)

        started = client.post("/api/start", json={"candidate_name": "dev@example.com"}).json()
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

    def test_custom_question_bootstraps_general_skill(self, client, monkeypatch):
        import evaluators.judge as judge_mod

        monkeypatch.setattr(judge_mod, "LLMJudge", FakeJudge)
        started = client.post("/api/start", json={
            "candidate_name": "interview@example.com",
            "initial_question": "Explain what a cache eviction policy is.",
        }).json()
        assert started["learner"]["primary_node_slug"] == "general"

    def test_report_includes_learner_snapshot(self, client, monkeypatch):
        import evaluators.judge as judge_mod

        monkeypatch.setattr(judge_mod, "LLMJudge", FakeJudge)
        started = client.post("/api/start", json={"candidate_name": "final@example.com"}).json()
        task = started["first_task"]
        client.post("/api/submit", json={
            "session_id": started["session_id"],
            "task_id": task["id"],
            "answer": "def f(): pass",
            "hints_used": [],
        })
        report = client.post("/api/report", json={"session_id": started["session_id"]}).json()
        assert report["learner"] is not None
        assert isinstance(report["learner"]["states"], dict)
        assert isinstance(report["learner"]["frontier_top"], list)
        assert isinstance(report["learner"]["misconceptions"], list)

    def test_guest_start_also_records_learner(self, client):
        # Override auth to anonymous so /start creates a guest (practice) session.
        import backend.auth as auth_mod

        original = auth_mod.user_from_token
        auth_mod.user_from_token = lambda token: None
        try:
            res = client.post("/api/start", json={"candidate_name": "Guest"})
        finally:
            auth_mod.user_from_token = original
        assert res.status_code == 200
        assert res.json()["learner"] is not None