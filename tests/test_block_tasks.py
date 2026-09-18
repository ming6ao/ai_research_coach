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

    # At least one part is required (no partless tasks).
    with pytest.raises(ValueError, match="At least one part"):
        create_task(owner="tester@example.com", parts=[])
    with pytest.raises(ValueError, match="At least one part"):
        create_task(owner="tester@example.com")

    # Duplicate keys rejected.
    with pytest.raises(ValueError):
        create_task(
            owner="tester@example.com", parts=[
                {"key": "a", "prompt": "p", "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2},
                {"key": "a", "prompt": "q", "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2},
            ]
        )
    # Empty prompt rejected.
    with pytest.raises(ValueError):
        create_task(
            owner="tester@example.com", parts=[
                {"key": "a", "prompt": "", "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2},
            ]
        )
    # Unknown tag rejected with a part-scoped message.
    with pytest.raises(ValueError, match="Part 'a'"):
        create_task(
            owner="tester@example.com", parts=[
                {"key": "a", "prompt": "p", "tags": {"primary": "bogus"}, "max_score": 5, "difficulty": 2},
            ]
        )


def test_prompt_is_derived_from_first_step(tmp_path, monkeypatch):
    """There is no authored overview: the task prompt is the first step's."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "derived.db")
    from coach.tasks import create_task, get_task

    t = create_task(
        owner="tester@example.com",
        tags={"primary": "testing"},
        parts=[
            {"key": "a", "prompt": "Implement the allocator.",
             "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2},
            {"key": "b", "prompt": "Now free the blocks.",
             "tags": {"primary": "testing"}, "max_score": 5, "difficulty": 2},
        ],
    )
    assert t["prompt"] == "Implement the allocator."
    assert get_task(t["id"])["prompt"] == "Implement the allocator."


def test_single_part_task(tmp_path, monkeypatch):
    """A single-step question is just a task with one part."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "single.db")
    from coach.tasks import create_task, get_task, single_part

    t = create_task(
        owner="tester@example.com",
        parts=[single_part("Implement def f(x): return x.", tags={"primary": "testing"})],
    )
    parts = get_task(t["id"])["parts"]
    assert len(parts) == 1
    assert parts[0]["prompt"] == t["prompt"] == "Implement def f(x): return x."


def test_block_aggregates_and_derives_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "block.db")
    from coach.tasks import create_task, get_task

    t = create_task(
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
    # No signature in the prompt: emit a neutral TODO, never a function named
    # after the internal step key (``def g(*args)`` reads as a real API).
    assert "def g(*args):" not in stub
    assert stub.count("# TODO") == 2


def test_scaffold_auto_composition_prefers_prompt_reference():
    from coach.session import build_code_stub

    task = {
        "id": "x", "prompt": "A block.",
        "parts": [
            {"key": "q", "prompt": "Implement `quantize_int8(values, scale)`."},
            {"key": "r", "prompt": "Implement `dequantize_int8`."},
            {"key": "s", "prompt": "Given `x` and `W1`, return the result."},
        ],
    }
    stub = build_code_stub(task)
    assert "def quantize_int8(values, scale):" in stub
    # Backticked data names (``x``, ``W1``) must not become function names, and
    # a bare ``Implement `name``` without params falls back to a neutral TODO.
    assert "def x(" not in stub and "def W1(" not in stub
    assert "def dequantize_int8(" not in stub
    assert stub.count("# TODO") == 3


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
