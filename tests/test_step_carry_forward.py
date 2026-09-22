"""Previous-step carry-forward: a later step with no starter code continues.

The first step always carries starter code. A later step may omit it, in which
case the editor opens from the immediately previous step's complete judge
solution. An authored scaffold always wins; there is no way to point at an
arbitrary earlier step.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import coach.db as db
from coach.judge import CoachContent, EvaluationResult

TAGS = {"primary": "testing"}


class ScriptedJudge:
    """Judge that returns a scripted solution per scored step."""

    def __init__(self, solutions: list[str] | None = None):
        self.solutions = list(solutions or [])
        self.calls = 0

    def evaluate(self, task, answer):
        from coach.judge import score_targets

        targets = score_targets(task)
        solution = self.solutions.pop(0) if self.solutions else ""
        parts = []
        total = 0.0
        for p in targets:
            total += float(p["max_score"])
            parts.append({"key": p["key"], "score": float(p["max_score"]), "rationale": "r"})
        max_score = sum(int(p["max_score"]) for p in targets)
        coach = CoachContent(feedback="f", steps=[], solution=solution)
        self.calls += 1
        return (
            EvaluationResult(task["id"], total, max_score, "r", coach.to_dict(), parts),
            coach,
        )


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Keep these tests offline: no session title/summary LLM call."""
    import coach.task_decomposer as td_mod

    monkeypatch.setattr(
        td_mod.TaskDecomposer, "describe_session", lambda self, task, answer: {}
    )


def _part(key: str, *, scaffold: str | None = None, scaffolds: dict | None = None) -> dict:
    part = {
        "key": key,
        "prompt": f"Implement {key}.",
        "tags": TAGS,
        "max_score": 5,
        "difficulty": 2,
    }
    if scaffold is not None:
        part["scaffold"] = scaffold
    if scaffolds is not None:
        part["scaffolds"] = scaffolds
    return part


def _make_task(task_id: str, parts: list[dict], *, languages=None) -> dict:
    from coach.tasks import create_task

    kwargs = {"languages": languages} if languages else {}
    return create_task(
        owner="bank@example.com",
        source="user",
        is_public=True,
        task_id=task_id,
        parts=parts,
        **kwargs,
    )


def _start(client, task_ids):
    res = client.post("/api/v1/sessions", json={"task_ids": task_ids})
    assert res.status_code == 201
    return res.json()["data"]


def _answer(client, session_id, task_id, answer, language=None):
    payload = {"task_id": task_id, "answer": answer}
    if language:
        payload["language"] = language
    res = client.post(f"/api/v1/sessions/{session_id}/answers", json=payload)
    assert res.status_code == 200
    return res.json()["data"]


# --------------------------------------------------------------------------
# Validation / storage
# --------------------------------------------------------------------------


def test_first_step_needs_starter_code():
    from coach.tasks import validate_parts

    with pytest.raises(ValueError, match="needs a scaffold"):
        validate_parts([_part("p1")])


def test_later_step_may_omit_starter_code():
    from coach.tasks import validate_parts

    parts = validate_parts([_part("p1", scaffold="a"), _part("p2")])
    assert parts[0]["scaffold"] == "a"
    assert "scaffold" not in parts[1]
    assert "scaffolds" not in parts[1]


def test_later_step_may_still_provide_starter_code():
    from coach.tasks import validate_parts

    parts = validate_parts([_part("p1", scaffold="a"), _part("p2", scaffold="b")])
    assert parts[1]["scaffold"] == "b"


def test_partial_scaffold_on_a_later_step_is_allowed():
    from coach.tasks import validate_parts

    parts = validate_parts(
        [
            _part("p1", scaffolds={"python": "x", "cpp": "y"}),
            _part("p2", scaffolds={"python": "only-python"}),
        ],
        languages=["python", "cpp"],
    )
    assert parts[1]["scaffolds"] == {"python": "only-python"}
    assert parts[1]["scaffold"] == "only-python"


def test_partial_scaffold_on_the_first_step_is_rejected():
    from coach.tasks import validate_parts

    with pytest.raises(ValueError, match="needs a scaffold for: cpp"):
        validate_parts(
            [_part("p1", scaffolds={"python": "x"})],
            languages=["python", "cpp"],
        )


def test_parse_parts_keeps_a_scaffoldless_step():
    from coach.tasks import parse_parts, serialize_parts, validate_parts

    parts = validate_parts([_part("p1", scaffold="a"), _part("p2")])
    stored = parse_parts(serialize_parts(parts))
    assert stored[0]["scaffold"] == "a"
    assert "scaffold" not in stored[1]


def test_create_task_round_trips_a_scaffoldless_step():
    task = _make_task("carry_01", [_part("p1", scaffold="a"), _part("p2")])
    assert task["parts"][0]["scaffold"] == "a"
    assert "scaffold" not in task["parts"][1]


# --------------------------------------------------------------------------
# Runtime resolution
# --------------------------------------------------------------------------


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "carry.db")
    import coach.judge as judge_mod

    judge = ScriptedJudge(
        solutions=["def p1(x):\n    return x + 1", "def p2(x):\n    return x + 2"]
    )
    monkeypatch.setattr(judge_mod, "LLMJudge", lambda: judge)
    _make_task(
        "carry_01",
        [
            _part("p1", scaffold="def p1(x):\n    pass\n"),
            _part("p2"),
            _part("p3"),
        ],
    )
    _make_task(
        "scaffolded_01",
        [
            _part("p1", scaffold="def p1(x):\n    pass\n"),
            _part("p2", scaffold="def p2(x):\n    # own stub\n    pass\n"),
        ],
    )
    from backend.main import app

    return TestClient(app), judge


def test_step_opens_from_previous_solution(ctx):
    client, judge = ctx
    data = _start(client, ["carry_01"])
    assert "def p1" in data["current_task"]["scaffold"]

    r = _answer(client, data["id"], "carry_01", "MY P1")
    nxt = r["next_task"]
    assert nxt["phase_index"] == 2
    assert nxt["scaffold"] == "def p1(x):\n    return x + 1"
    assert nxt["starts_from_previous"] is True


def test_resume_reopens_from_previous_solution(ctx):
    client, judge = ctx
    data = _start(client, ["carry_01"])
    _answer(client, data["id"], "carry_01", "MY P1")

    resume = client.get(f"/api/v1/sessions/{data['id']}").json()["data"]
    task = resume["current_task"]
    assert task["phase_index"] == 2
    assert task["scaffold"] == "def p1(x):\n    return x + 1"
    assert task["starts_from_previous"] is True


def test_third_step_uses_the_immediately_previous_solution(ctx):
    client, judge = ctx
    data = _start(client, ["carry_01"])
    _answer(client, data["id"], "carry_01", "ONE")
    second = _answer(client, data["id"], "carry_01", "TWO")
    # Step 3 continues from step 2's solution, not step 1's.
    assert second["next_task"]["scaffold"] == "def p2(x):\n    return x + 2"


def test_authored_scaffold_wins_over_previous_solution(ctx):
    client, judge = ctx
    data = _start(client, ["scaffolded_01"])
    r = _answer(client, data["id"], "scaffolded_01", "MY P1")
    nxt = r["next_task"]
    assert nxt["phase_index"] == 2
    assert nxt["scaffold"] == "def p2(x):\n    # own stub\n    pass"
    assert "starts_from_previous" not in nxt


def test_missing_solution_falls_back_to_composed_stub(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "carry_fallback.db")
    import coach.judge as judge_mod

    judge = ScriptedJudge(solutions=[""])  # judge produced no solution
    monkeypatch.setattr(judge_mod, "LLMJudge", lambda: judge)
    _make_task(
        "carry_fb",
        [
            _part("p1", scaffold="def p1():\n    pass\n"),
            {"key": "p2", "prompt": "Extend the previous implementation.",
             "tags": TAGS, "max_score": 5, "difficulty": 2},
        ],
    )
    from backend.main import app

    client = TestClient(app)
    data = _start(client, ["carry_fb"])
    r = _answer(client, data["id"], "carry_fb", "MY P1")
    nxt = r["next_task"]
    # No solution, no authored scaffold -> best-effort composed stub.
    assert "TODO" in nxt["scaffold"]
    assert "starts_from_previous" not in nxt


def test_multi_language_uses_the_previous_solution_in_the_locked_language(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "carry_multi.db")
    import coach.judge as judge_mod

    judge = ScriptedJudge(solutions=["PREVIOUS CPP SOLUTION"])
    monkeypatch.setattr(judge_mod, "LLMJudge", lambda: judge)
    _make_task(
        "carry_multi",
        [
            _part("p1", scaffolds={"python": "py stub", "cpp": "cpp stub"}),
            _part("p2"),
        ],
        languages=["python", "cpp"],
    )
    from backend.main import app

    client = TestClient(app)
    data = _start(client, ["carry_multi"])
    r = _answer(client, data["id"], "carry_multi", "CPP CODE", language="cpp")
    nxt = r["next_task"]
    assert nxt["language"] == "cpp"
    assert nxt["scaffold"] == "PREVIOUS CPP SOLUTION"
    assert nxt["scaffolds"]["cpp"] == "PREVIOUS CPP SOLUTION"
    # The other declared language has no recorded solution: composed stub.
    assert nxt["scaffolds"]["python"] != "PREVIOUS CPP SOLUTION"
    assert nxt["starts_from_previous"] is True


def test_partial_scaffold_falls_back_per_language(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "carry_partial.db")
    import coach.judge as judge_mod

    judge = ScriptedJudge(solutions=["PREVIOUS CPP SOLUTION"])
    monkeypatch.setattr(judge_mod, "LLMJudge", lambda: judge)
    _make_task(
        "carry_partial",
        [
            _part("p1", scaffolds={"python": "py stub", "cpp": "cpp stub"}),
            # Only Python starter code; C++ must inherit the previous solution.
            _part("p2", scaffolds={"python": "def p2():\n    pass\n"}),
        ],
        languages=["python", "cpp"],
    )
    from backend.main import app

    client = TestClient(app)
    data = _start(client, ["carry_partial"])
    r = _answer(client, data["id"], "carry_partial", "CPP CODE", language="cpp")
    nxt = r["next_task"]
    assert nxt["language"] == "cpp"
    # C++ has no authored stub, so it continues from the previous solution;
    # Python keeps the stub the curator wrote for this step.
    assert nxt["scaffold"] == "PREVIOUS CPP SOLUTION"
    assert nxt["scaffolds"]["cpp"] == "PREVIOUS CPP SOLUTION"
    assert nxt["scaffolds"]["python"] == "def p2():\n    pass"
    assert nxt["starts_from_previous"] is True
