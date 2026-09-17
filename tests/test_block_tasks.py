"""Code-block tasks: parts validation, scaffold auto-composition, and judge
per-part scoring targets.
"""

from __future__ import annotations

import pytest

import coach.db as db
from coach.judge import EvaluationResult, score_targets


def test_parts_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "parts.db")
    from coach.tasks import create_task

    # Duplicate keys rejected.
    with pytest.raises(ValueError):
        create_task(
            prompt="b", owner="tester@example.com", parts=[
                {"key": "a", "prompt": "p", "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2},
                {"key": "a", "prompt": "q", "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2},
            ]
        )
    # Empty prompt rejected.
    with pytest.raises(ValueError):
        create_task(
            prompt="b", owner="tester@example.com", parts=[
                {"key": "a", "prompt": "", "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2},
            ]
        )
    # Unknown tag rejected with a part-scoped message.
    with pytest.raises(ValueError, match="Part 'a'"):
        create_task(
            prompt="b", owner="tester@example.com", parts=[
                {"key": "a", "prompt": "p", "tags": {"primary": "bogus"}, "max_score": 5, "difficulty": 2},
            ]
        )


def test_block_aggregates_and_derives_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "block.db")
    from coach.tasks import create_task, get_task

    t = create_task(
        prompt="Two-part block.",
        owner="bank@example.com",
        source="user",
        is_public=True,
        parts=[
            {"key": "a", "prompt": "def a(x): ...", "tags": {"primary": "vision_encoders"},
             "max_score": 5, "difficulty": 3},
            {"key": "b", "prompt": "def b(y): ...", "tags": {"primary": "state_space_models"},
             "max_score": 5, "difficulty": 4},
        ],
    )
    assert t["max_score"] == 10  # aggregate
    assert t["difficulty"] == 4  # max part difficulty when omitted
    assert t["tags"]["primary"] == "vision_encoders"  # auto-derived
    assert t["tags"]["secondary"] == ["state_space_models"]
    assert get_task(t["id"])["parts"][1]["key"] == "b"


def test_scaffold_auto_composition():
    from coach.session import build_code_stub

    task = {
        "id": "x", "prompt": "A block.",
        "parts": [
            {"key": "f", "prompt": "Implement def f(x, y): ..."},
            {"key": "g", "prompt": "Return the pairs."},
        ],
    }
    stub = build_code_stub(task)
    assert "def f(x, y):" in stub
    assert "def g(*args):" in stub  # fallback for parts without a signature


def test_score_targets():
    task = {
        "id": "x", "prompt": "p",
        "parts": [{"key": "a", "prompt": "pa", "tags": {"primary": "vision_encoders"},
                   "max_score": 5, "difficulty": 2}],
    }
    assert score_targets(task)[0]["key"] == "a"
    assert score_targets(task)[0]["tags"]["primary"] == "vision_encoders"


def test_answer_for_task(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "af.db")
    from coach.steps import answer_for_task, insert_step

    insert_step(
        "s", "c", 0, {"id": "t"}, "bank", "code-here", 5, 5, 1.0, 1.0,
        None, None, {}, None,
    )
    assert answer_for_task("s", "t") == "code-here"
    assert answer_for_task("s", "nope") is None