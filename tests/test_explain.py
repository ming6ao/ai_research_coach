"""Selection-driven explanations: create/list/dedup + session cleanup.

The LLM is stubbed so the suite is hermetic (conftest clears GOOGLE_API_KEY).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import coach.db as db


class StubExplainer:
    """Records calls and returns a canned explanation."""

    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def explain(self, selection, **kwargs):
        type(self).calls += 1
        assert selection
        return {
            "title": "Gradient descent",
            "explanation": "It steps downhill. $$x_{t+1} = x_t - \\eta g$$",
            "related_terms": ["learning rate", "gradient"],
        }


class FailingExplainer:
    def __init__(self, *args, **kwargs):
        pass

    def explain(self, selection, **kwargs):
        raise RuntimeError("boom")


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "explain.db")
    from coach.tasks import create_task

    create_task(
        owner="bank@example.com",
        source="user",
        is_public=True,
        task_id="explain_01",
        parts=[
            {
                "key": "p1",
                "prompt": "Implement def p1(x): ...",
                "tags": {"primary": "vision_encoders"},
                "max_score": 5,
                "difficulty": 2,
            }
        ],
    )
    from backend.main import app

    return TestClient(app)


def _start(client):
    res = client.post("/api/v1/sessions", json={"task_ids": ["explain_01"]})
    assert res.status_code == 201
    return res.json()["data"]


def test_create_and_list_explanation(ctx, monkeypatch):
    import coach.explainer as explainer_mod

    monkeypatch.setattr(explainer_mod, "Explainer", StubExplainer)
    StubExplainer.calls = 0
    data = _start(ctx)
    res = ctx.post(
        f"/api/v1/sessions/{data['id']}/explanations",
        json={
            "task_id": "explain_01",
            "step_key": "p1",
            "selected_text": "gradient descent",
            "context": "We minimize the loss.",
            "source_kind": "question",
        },
    )
    assert res.status_code == 201, res.text
    row = res.json()["data"]
    assert row["title"] == "Gradient descent"
    assert row["cached"] is False
    assert row["related_terms"] == ["learning rate", "gradient"]
    assert row["session_id"] == data["id"]

    listed = ctx.get(f"/api/v1/sessions/{data['id']}/explanations").json()
    assert listed["meta"]["total"] == 1
    assert listed["data"][0]["id"] == row["id"]


def test_identical_request_is_cached(ctx, monkeypatch):
    import coach.explainer as explainer_mod

    monkeypatch.setattr(explainer_mod, "Explainer", StubExplainer)
    StubExplainer.calls = 0
    data = _start(ctx)
    body = {
        "task_id": "explain_01",
        "step_key": "p1",
        "selected_text": "gradient descent",
        "source_kind": "question",
    }
    first = ctx.post(f"/api/v1/sessions/{data['id']}/explanations", json=body)
    second = ctx.post(f"/api/v1/sessions/{data['id']}/explanations", json=body)
    assert first.status_code == 201 and second.status_code == 201
    assert second.json()["data"]["cached"] is True
    assert second.json()["data"]["id"] == first.json()["data"]["id"]
    assert StubExplainer.calls == 1


def test_empty_and_oversize_selection_are_rejected(ctx):
    data = _start(ctx)
    empty = ctx.post(
        f"/api/v1/sessions/{data['id']}/explanations",
        json={"task_id": "explain_01", "selected_text": ""},
    )
    assert empty.status_code == 422
    huge = ctx.post(
        f"/api/v1/sessions/{data['id']}/explanations",
        json={"task_id": "explain_01", "selected_text": "x" * 4001},
    )
    assert huge.status_code == 422


def test_unknown_task_is_404(ctx):
    data = _start(ctx)
    res = ctx.post(
        f"/api/v1/sessions/{data['id']}/explanations",
        json={"task_id": "nope", "selected_text": "x"},
    )
    assert res.status_code == 404


def test_llm_failure_returns_502(ctx, monkeypatch):
    import coach.explainer as explainer_mod

    monkeypatch.setattr(explainer_mod, "Explainer", FailingExplainer)
    data = _start(ctx)
    res = ctx.post(
        f"/api/v1/sessions/{data['id']}/explanations",
        json={"task_id": "explain_01", "selected_text": "x"},
    )
    assert res.status_code == 502


def test_followup_grounds_in_parent(ctx, monkeypatch):
    import coach.explainer as explainer_mod

    monkeypatch.setattr(explainer_mod, "Explainer", StubExplainer)
    StubExplainer.calls = 0
    data = _start(ctx)
    root = ctx.post(
        f"/api/v1/sessions/{data['id']}/explanations",
        json={"task_id": "explain_01", "selected_text": "gradient descent"},
    ).json()["data"]
    follow = ctx.post(
        f"/api/v1/sessions/{data['id']}/explanations",
        json={
            "task_id": "explain_01",
            "selected_text": "learning rate",
            "parent_id": root["id"],
            "question": "Why does the learning rate matter?",
        },
    )
    assert follow.status_code == 201, follow.text
    assert follow.json()["data"]["parent_id"] == root["id"]
    # A follow-up is never served from the dedup cache.
    assert follow.json()["data"]["cached"] is False


def test_session_delete_removes_explanations(ctx, monkeypatch):
    import coach.explainer as explainer_mod

    monkeypatch.setattr(explainer_mod, "Explainer", StubExplainer)
    data = _start(ctx)
    ctx.post(
        f"/api/v1/sessions/{data['id']}/explanations",
        json={"task_id": "explain_01", "selected_text": "gradient descent"},
    )
    from coach.explanations import list_explanations

    assert len(list_explanations(data["id"])) == 1
    assert ctx.delete(f"/api/v1/sessions/{data['id']}").status_code == 204
    assert list_explanations(data["id"]) == []
