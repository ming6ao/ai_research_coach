"""Multi-language tasks: Python + C++ answers with per-language starter code.

One task may declare several accepted languages; every step must carry a
scaffold for each declared language. The candidate picks a language, which is
locked after the first submission, and each step starts from that language's
own scaffold. Single-language tasks keep the legacy ``scaffold``/``language``
shape.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import coach.db as db
from coach.judge import CoachContent, EvaluationResult


class RecordingJudge:
    """Judge that records the language it was called with."""

    def __init__(self):
        self.calls: list[str | None] = []

    def evaluate(self, task, answer):
        from coach.judge import score_targets

        self.calls.append(task.get("language"))
        targets = score_targets(task)
        parts = [
            {"key": p["key"], "score": p["max_score"], "rationale": "ok"}
            for p in targets
        ]
        total = sum(int(p["max_score"]) for p in targets)
        coach = CoachContent(feedback="", misconception="", steps=[])
        return (
            EvaluationResult(task["id"], total, total, "r", coach.to_dict(), parts),
            coach,
        )


MULTI_PARTS = [
    {
        "key": "tiled",
        "prompt": "Implement tiled attention.",
        "tags": {"primary": "flash_attention", "secondary": []},
        "max_score": 6,
        "difficulty": 3,
        "scaffolds": {
            "python": "import torch\n\ndef tiled(Q, K, V, block):\n    pass\n",
            "cpp": "// TODO\ntorch::Tensor tiled(torch::Tensor Q, torch::Tensor K);\n",
        },
    },
    {
        "key": "causal",
        "prompt": "Add causal masking.",
        "tags": {"primary": "flash_attention", "secondary": []},
        "max_score": 6,
        "difficulty": 4,
        "scaffolds": {
            "python": "def causal(Q, K, V, block):\n    pass\n",
            "cpp": "// TODO\ntorch::Tensor causal(torch::Tensor Q, torch::Tensor K);\n",
        },
    },
]


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "multilang.db")
    import coach.judge as judge_mod

    judge = RecordingJudge()
    monkeypatch.setattr(judge_mod, "LLMJudge", lambda: judge)
    from coach.tasks import create_task

    create_task(
        owner="bank@example.com",
        source="user",
        is_public=True,
        task_id="multi_01",
        languages=["python", "cpp"],
        parts=MULTI_PARTS,
    )
    from backend.main import app

    return TestClient(app), judge


def _start(client, task_ids):
    res = client.post("/api/v1/sessions", json={"task_ids": task_ids})
    assert res.status_code == 201
    return res.json()["data"]


def _answer(client, session_id, task_id, answer, language=None):
    body = {"task_id": task_id, "answer": answer}
    if language:
        body["language"] = language
    res = client.post(f"/api/v1/sessions/{session_id}/answers", json=body)
    assert res.status_code == 200
    return res.json()["data"]


def test_create_stores_languages_and_per_language_scaffolds(ctx):
    from coach.tasks import get_task

    task = get_task("multi_01")
    assert task["language"] == "python"
    assert task["languages"] == ["python", "cpp"]
    # Default-language scaffold is mirrored on the legacy field.
    assert task["parts"][0]["scaffold"].startswith("import torch")
    assert set(task["parts"][0]["scaffolds"]) == {"python", "cpp"}


def test_missing_scaffold_for_declared_language_is_rejected():
    from coach.tasks import create_task

    with pytest.raises(ValueError, match="scaffold for: cpp"):
        create_task(
            owner="bank@example.com",
            source="user",
            is_public=True,
            task_id="multi_bad",
            languages=["python", "cpp"],
            parts=[
                {
                    "key": "tiled",
                    "prompt": "Implement tiled attention.",
                    "tags": {"primary": "flash_attention"},
                    "max_score": 6,
                    "difficulty": 3,
                    "scaffold": "def tiled(Q, K, V, block):\n    pass\n",
                }
            ],
        )


def test_create_via_api_round_trips_languages(ctx):
    client, _ = ctx
    res = client.post(
        "/api/v1/tasks",
        json={
            "languages": ["python", "cpp"],
            "parts": MULTI_PARTS,
            "is_public": True,
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["languages"] == ["python", "cpp"]
    assert set(data["parts"][0]["scaffolds"]) == {"python", "cpp"}

    res = client.post(
        "/api/v1/tasks",
        json={
            "languages": ["python", "cpp"],
            "parts": [
                {
                    "key": "tiled",
                    "prompt": "Implement tiled attention.",
                    "tags": {"primary": "flash_attention"},
                    "max_score": 6,
                    "difficulty": 3,
                    "scaffold": "def tiled(Q, K, V, block):\n    pass\n",
                }
            ],
        },
    )
    assert res.status_code == 422
    assert "cpp" in res.json()["detail"]


def test_view_exposes_languages_and_scaffolds(ctx):
    client, _ = ctx
    data = _start(client, ["multi_01"])
    task = data["current_task"]
    assert task["languages"] == ["python", "cpp"]
    assert set(task["scaffolds"]) == {"python", "cpp"}
    assert task["scaffolds"]["cpp"].startswith("// TODO")


def test_chosen_language_flows_to_judge_and_is_locked(ctx):
    client, judge = ctx
    data = _start(client, ["multi_01"])

    first = _answer(client, data["id"], "multi_01", "CPP STEP 1", language="cpp")
    assert first["language"] == "cpp"
    assert judge.calls[-1] == "cpp"

    # Step 2 is a new step of the same task: the language stays locked to cpp
    # even when the client asks for python.
    second = _answer(client, data["id"], "multi_01", "PY STEP 2", language="python")
    assert second["language"] == "cpp"
    assert judge.calls[-1] == "cpp"


def test_next_step_uses_its_own_scaffold(ctx):
    from coach.steps import list_steps

    client, judge = ctx
    data = _start(client, ["multi_01"])
    first = _answer(client, data["id"], "multi_01", "PY STEP 1", language="python")

    nxt = first["next_task"]
    assert nxt["id"] == "multi_01"
    assert nxt["phase_index"] == 2
    # The second step starts from its own starter code; nothing is carried
    # forward from the first answer.
    assert "previous_code" not in nxt
    assert nxt["scaffold"].startswith("def causal")
    assert nxt["scaffolds"]["python"].startswith("def causal")

    _answer(client, data["id"], "multi_01", "PY STEP 2", language="python")
    steps = list_steps(data["id"])
    assert [s["language"] for s in steps] == ["python", "python"]
    assert judge.calls == ["python", "python"]


def test_default_language_used_when_none_requested(ctx):
    client, judge = ctx
    data = _start(client, ["multi_01"])
    res = _answer(client, data["id"], "multi_01", "PY CODE")
    assert res["language"] == "python"
    assert judge.calls[-1] == "python"


def test_resume_reports_locked_language(ctx):
    client, _ = ctx
    data = _start(client, ["multi_01"])
    _answer(client, data["id"], "multi_01", "CPP1", language="cpp")

    resume = client.get(f"/api/v1/sessions/{data['id']}").json()["data"]
    task = resume["current_task"]
    assert task["phase_index"] == 2
    # Reopens in the locked language, showing the second step's own scaffold
    # rather than the first answer.
    assert task["language"] == "cpp"
    assert "previous_code" not in task
    assert task["scaffolds"]["cpp"].startswith("// TODO")


def test_followup_inherits_root_languages():
    """A judge-driven drill keeps the root task's language set."""
    from coach.remediation import RemediationPlanner

    class FakeDecomposer:
        def generate_followup_task(self, target, original_task, difficulty, mode, extra_context=""):
            return {
                "id": "remed_test",
                "type": "code",
                "difficulty": difficulty,
                "prompt": "Simpler drill.",
                "max_score": 5,
                "parts": [{"key": "solution", "prompt": "Simpler drill.", "tags": {}, "max_score": 5, "difficulty": difficulty}],
                "generated": True,
            }

    class FakeSession:
        candidate = "cand@example.com"

        def get_ability(self):
            class A:
                score = 0.4
            return A()

    planner = RemediationPlanner.__new__(RemediationPlanner)
    planner.decomposer = FakeDecomposer()
    root = {
        "id": "multi_01",
        "difficulty": 4,
        "languages": ["python", "cpp"],
        "language": "python",
        "prompt": "Tiled attention.",
        "tags": {"primary": "flash_attention"},
    }
    task = {
        "id": "multi_01",
        "difficulty": 4,
        "generated": False,
        "languages": ["python", "cpp"],
        "language": "python",
        "prompt": "Tiled attention.",
        "tags": {"primary": "flash_attention"},
    }
    # `_generate` needs a session-like object for difficulty tuning; drive the
    # public path with the minimal collaborators it touches.
    generated = planner._generate(
        FakeSession(), task, root, "your rescaling", 3, mode="remediate"
    )
    assert generated["languages"] == ["python", "cpp"]
    assert generated["language"] == "python"
