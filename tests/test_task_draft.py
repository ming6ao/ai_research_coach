"""Curator quick authoring: draft/refine endpoint + LLM output sanitization."""

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth
import coach.db as db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "draft.db")
    from backend.main import app

    return TestClient(app)


def _login(email, name="T"):
    user = auth.upsert_google_user(email, name)
    return auth.create_token(user["id"])


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_draft_requires_auth(client):
    res = client.post("/api/v1/tasks/draft", json={"steps": ["Do x."]})
    assert res.status_code == 401


def test_draft_offline_fallback_shapes_parts(client):
    token = _login("draft@x.com")
    res = client.post(
        "/api/v1/tasks/draft",
        json={"steps": ["Implement foo(x, y) that adds.", "Handle None inputs."]},
        headers=_h(token),
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert [p["prompt"] for p in data["parts"]] == [
        "Implement foo(x, y) that adds.",
        "Handle None inputs.",
    ]
    assert data["language"] == "python"
    assert data["task_type"] == "implement"
    # The reason no starter code/tags were invented is surfaced, not swallowed.
    assert data["problems"] and "GOOGLE_API_KEY" in data["problems"][0]
    for part in data["parts"]:
        assert part["max_score"] == 5
        assert part["difficulty"] == 2
        assert part["pass_score"] == 4
        assert part["tags"]["primary"] == ""  # offline: curator picks the skill


def test_draft_does_not_synthesize_offline_scaffold(client):
    token = _login("draft@x.com")
    res = client.post(
        "/api/v1/tasks/draft",
        json={"steps": ["Implement `def stft(x, n_fft)`: return the STFT."]},
        headers=_h(token),
    )
    assert res.status_code == 200, res.text
    # No LLM (missing key): no starter code is invented, so the curator editor
    # can block creation until the step has a scaffold.
    data = res.json()["data"]
    assert "scaffold" not in data["parts"][0]
    # No key -> the curator must be told the assistant could not fill this in.
    assert data["problems"]


def test_draft_rejects_empty_steps(client):
    token = _login("draft@x.com")
    res = client.post("/api/v1/tasks/draft", json={"steps": []}, headers=_h(token))
    assert res.status_code == 422


def test_draft_rejects_more_than_five_steps(client):
    token = _login("draft@x.com")
    res = client.post(
        "/api/v1/tasks/draft",
        json={"steps": [f"Step {i}" for i in range(6)]},
        headers=_h(token),
    )
    assert res.status_code == 422


def test_draft_requires_steps_or_refinement(client):
    token = _login("draft@x.com")
    assert client.post("/api/v1/tasks/draft", json={}, headers=_h(token)).status_code == 422
    empty_draft = client.post(
        "/api/v1/tasks/draft", json={"draft": {"parts": []}}, headers=_h(token)
    )
    assert empty_draft.status_code == 422


def test_draft_refinement_offline_preserves_draft(client):
    token = _login("draft@x.com")
    draft = {
        "parts": [
            {"key": "a", "prompt": "Original A", "tags": {"primary": "testing"},
             "max_score": 5, "difficulty": 2},
        ],
        "language": "python",
        "task_type": "implement",
        "context_notes": "keep me",
    }
    res = client.post(
        "/api/v1/tasks/draft",
        json={"draft": draft, "instruction": "Make it harder"},
        headers=_h(token),
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["context_notes"] == "keep me"
    assert data["parts"][0]["prompt"] == "Original A"
    assert data["parts"][0]["tags"]["primary"] == "testing"


def test_draft_route_serializes_decomposer_output(client, monkeypatch):
    token = _login("draft@x.com")
    from coach.task_decomposer import TaskDecomposer

    def fake_draft_task(self, steps=None, **kwargs):
        return {
            "parts": [
                {"key": "k", "prompt": "P", "tags": {"primary": "testing", "secondary": []},
                 "max_score": 5, "difficulty": 2, "pass_score": 4}
            ],
            "language": "python",
            "task_type": "implement",
            "context_notes": "notes",
            "tags": {"primary": "testing", "secondary": []},
        }

    monkeypatch.setattr(TaskDecomposer, "draft_task", fake_draft_task)
    res = client.post("/api/v1/tasks/draft", json={"steps": ["x"]}, headers=_h(token))
    assert res.status_code == 200, res.text
    assert res.json()["data"]["context_notes"] == "notes"


def test_draft_task_sanitizes_and_retries(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    from coach.task_decomposer import TaskDecomposer

    decomposer = TaskDecomposer()
    responses = [
        {  # rejected: out-of-range scores, invented tag, implementation body
            "context_notes": "n",
            "task_type": "apply",
            "steps": [
                {"key": "foo", "prompt": "Do foo", "difficulty": 9, "max_score": 500,
                 "primary_tag": "bogus", "secondary_tag": ["testing"],
                 "scaffold": "def foo():\n    return 1\n"}
            ],
        },
        {  # accepted
            "context_notes": "n",
            "task_type": "apply",
            "steps": [
                {"key": "foo", "prompt": "Do foo", "difficulty": 3, "max_score": 8,
                 "primary_tag": "testing", "secondary_tag": ["caching"],
                 "scaffold": "def foo():\n    # TODO: implement foo\n    pass\n"}
            ],
        },
    ]
    calls = {"n": 0}

    def fake(body, *, refine, feedback=""):
        payload = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return payload

    monkeypatch.setattr(decomposer, "_generate_draft_payload", fake)
    out = decomposer.draft_task(steps=["Do foo"])
    assert calls["n"] == 2  # first rejected, retry succeeded
    part = out["parts"][0]
    assert part["difficulty"] == 3
    assert part["max_score"] == 8
    assert part["tags"] == {"primary": "testing", "secondary": ["caching"]}
    assert "# TODO" in part["scaffold"]


def test_strip_duplicate_signature_variants():
    from coach.task_decomposer import _strip_duplicate_signature

    scaffold = "def foo(x, y):\n    # TODO: implement foo\n    pass\n"
    assert (
        _strip_duplicate_signature("Implement `def foo(x, y)` that adds.", scaffold)
        == "Implement foo that adds."
    )
    assert (
        _strip_duplicate_signature("Write foo(x, y) that adds.", scaffold)
        == "Write foo that adds."
    )
    assert (
        _strip_duplicate_signature("Implement `foo(x, y)` that adds.", scaffold)
        == "Implement foo that adds."
    )
    # No scaffold (nothing to strip) or no duplication: unchanged.
    assert _strip_duplicate_signature("Just prose.", scaffold) == "Just prose."
    assert _strip_duplicate_signature("Just prose.", "") == "Just prose."


def test_draft_task_strips_signature_from_prompt(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    from coach.task_decomposer import TaskDecomposer

    decomposer = TaskDecomposer()

    def fake(body, *, refine, feedback=""):
        return {
            "steps": [
                {"key": "foo", "prompt": "Implement `def foo(x, y)` that adds.",
                 "primary_tag": "testing",
                 "scaffold": "def foo(x, y):\n    # TODO: implement foo\n    pass\n"}
            ]
        }

    monkeypatch.setattr(decomposer, "_generate_draft_payload", fake)
    out = decomposer.draft_task(steps=["Add two numbers."])
    assert out["parts"][0]["prompt"] == "Implement foo that adds."


def test_draft_task_leaves_missing_scaffold_empty(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    from coach.task_decomposer import TaskDecomposer

    decomposer = TaskDecomposer()

    def fake(body, *, refine, feedback=""):
        return {
            "steps": [
                {"key": "foo", "prompt": "Implement foo(x, y).", "primary_tag": "testing"}
            ]
        }

    monkeypatch.setattr(decomposer, "_generate_draft_payload", fake)
    out = decomposer.draft_task(steps=["Implement foo(x, y)."], retries=1)
    assert "scaffold" not in out["parts"][0]
    # The missing scaffold is reported so the editor can explain it.
    assert any("step 1" in p and "scaffold" in p for p in out["problems"])


def test_draft_task_reports_generation_failure(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    from coach.task_decomposer import TaskDecomposer

    decomposer = TaskDecomposer()

    def boom(body, *, refine, feedback=""):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(decomposer, "_generate_draft_payload", boom)
    out = decomposer.draft_task(steps=["Do foo"], retries=2)
    assert out["problems"] and "model exploded" in out["problems"][0]


def test_draft_task_drops_leaking_scaffold_after_retries(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    from coach.task_decomposer import TaskDecomposer

    decomposer = TaskDecomposer()

    def fake(body, *, refine, feedback=""):
        return {
            "steps": [
                {"key": "foo", "prompt": "Do foo", "primary_tag": "notreal",
                 "scaffold": "def foo():\n    return 1\n"}
            ]
        }

    monkeypatch.setattr(decomposer, "_generate_draft_payload", fake)
    out = decomposer.draft_task(steps=["Do foo"], retries=1)
    part = out["parts"][0]
    assert part["tags"]["primary"] == ""
    assert "return 1" not in part.get("scaffold", "")


def test_draft_task_allows_a_scaffoldless_later_step(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    from coach.task_decomposer import TaskDecomposer

    decomposer = TaskDecomposer()

    def fake(body, *, refine, feedback=""):
        return {
            "steps": [
                {"key": "foo", "prompt": "Do foo", "primary_tag": "testing",
                 "scaffold": "def foo():\n    # TODO\n    pass\n"},
                {"key": "bar", "prompt": "Extend foo", "primary_tag": "testing"},
            ]
        }

    monkeypatch.setattr(decomposer, "_generate_draft_payload", fake)
    out = decomposer.draft_task(steps=["Do foo", "Extend foo"])
    # The later step opens from the previous step's solution, so its missing
    # scaffold is not a problem.
    assert "scaffold" not in out["parts"][1]
    assert not any("scaffold" in p for p in out["problems"])


def test_draft_task_flags_a_scaffoldless_first_step(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    from coach.task_decomposer import TaskDecomposer

    decomposer = TaskDecomposer()

    def fake(body, *, refine, feedback=""):
        return {
            "steps": [
                {"key": "foo", "prompt": "Do foo", "primary_tag": "testing"}
            ]
        }

    monkeypatch.setattr(decomposer, "_generate_draft_payload", fake)
    out = decomposer.draft_task(steps=["Do foo"], retries=1)
    assert "scaffold" not in out["parts"][0]
    assert any("step 1" in p and "scaffold" in p for p in out["problems"])
