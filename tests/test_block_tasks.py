"""Code-block tasks + version chains (design doc): parts validation,
scaffold auto-composition, version-successor selection with code carry-forward,
and judge per-part scoring targets.
"""

from __future__ import annotations

import pytest

import coach.db as db
from coach.judge import EvaluationResult, score_targets


def _make_pred_succ():
    pred = {
        "id": "pred", "prompt": "Implement a plain queue. Signature: def put(item):",
        "difficulty": 2, "max_score": 5,
        "tags": {"primary": "data_structures", "secondary": []},
        "version_index": 1, "version_root_id": "pred",
    }
    succ = {
        "id": "succ", "prompt": "Make the queue thread-safe.",
        "difficulty": 4, "max_score": 5,
        "tags": {"primary": "data_structures", "secondary": []},
        "version_index": 2, "version_root_id": "pred", "depends_on_task_id": "pred",
    }
    return pred, succ


def test_parts_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "parts.db")
    from coach.tasks import create_task

    # Duplicate keys rejected.
    with pytest.raises(ValueError):
        create_task(
            prompt="b", parts=[
                {"key": "a", "prompt": "p", "tags": {"primary": "python"}, "max_score": 5, "difficulty": 2},
                {"key": "a", "prompt": "q", "tags": {"primary": "python"}, "max_score": 5, "difficulty": 2},
            ]
        )
    # Empty prompt rejected.
    with pytest.raises(ValueError):
        create_task(
            prompt="b", parts=[
                {"key": "a", "prompt": "", "tags": {"primary": "python"}, "max_score": 5, "difficulty": 2},
            ]
        )
    # Unknown tag rejected with a part-scoped message.
    with pytest.raises(ValueError, match="Part 'a'"):
        create_task(
            prompt="b", parts=[
                {"key": "a", "prompt": "p", "tags": {"primary": "bogus"}, "max_score": 5, "difficulty": 2},
            ]
        )


def test_block_aggregates_and_derives_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "block.db")
    from coach.tasks import create_task, get_task

    t = create_task(
        prompt="Two-part block.",
        owner="system",
        source="seed",
        is_public=True,
        parts=[
            {"key": "a", "prompt": "def a(x): ...", "tags": {"primary": "cnn"},
             "max_score": 5, "difficulty": 3},
            {"key": "b", "prompt": "def b(y): ...", "tags": {"primary": "rnn_lstm"},
             "max_score": 5, "difficulty": 4},
        ],
    )
    assert t["max_score"] == 10  # aggregate
    assert t["difficulty"] == 4  # max part difficulty when omitted
    assert t["tags"]["primary"] == "cnn"  # auto-derived
    assert t["tags"]["secondary"] == ["rnn_lstm"]
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


def test_version_successor_selected_with_code_carry_forward(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ver.db")
    from coach.selection import pick_next_task
    from coach.session import Session
    from coach.steps import insert_step

    pred, succ = _make_pred_succ()
    session = Session("c", tasks=[pred, succ])
    session.asked_task_ids.add("pred")
    session.results.append(EvaluationResult("pred", 5, 5, "ok"))
    insert_step(
        "sess", "c", 0, pred, "bank", "OLD QUEUE CODE", 5, 5, 1.0, 1.0, [],
        None, None, {}, None,
    )

    # After a submission the successor surfaces, with the predecessor's code
    # carried into the view.
    picked = pick_next_task(
        session.candidate, session,
        last_submission={"task": pred, "answer": "NEW QUEUE CODE"},
        session_id="sess",
    )
    assert picked is not None
    assert picked["id"] == "succ"
    assert picked["version_index"] == 2
    assert picked["version_total"] == 2
    assert picked["depends_on_task_id"] == "pred"
    assert picked["previous_code"] == "NEW QUEUE CODE"

    # Resume path (no last_submission): the predecessor code is fetched from
    # session_steps instead.
    picked2 = pick_next_task(session.candidate, session, session_id="sess")
    assert picked2 is not None
    assert picked2["id"] == "succ"
    assert picked2["previous_code"] == "OLD QUEUE CODE"


def test_successor_excluded_from_bank_picker():
    from coach.picker import next_task
    from coach.session import Session

    pred, succ = _make_pred_succ()
    other = {
        "id": "other", "prompt": "Another task.", "difficulty": 2, "max_score": 5,
        "tags": {"primary": "python", "secondary": []},
    }
    session = Session("c", tasks=[pred, succ, other])
    session.asked_task_ids.add("pred")
    # The successor must never be a bank candidate.
    for _ in range(3):
        chosen = next_task(session)
        assert chosen["id"] == "other"


def test_score_targets_blocks_and_legacy():
    block = {
        "id": "x", "prompt": "p",
        "parts": [{"key": "a", "prompt": "pa", "tags": {"primary": "cnn"},
                   "max_score": 5, "difficulty": 2}],
    }
    assert score_targets(block)[0]["key"] == "a"
    assert score_targets(block)[0]["tags"]["primary"] == "cnn"

    # A legacy single-question task becomes one implicit part named after the
    # function in the prompt.
    legacy = {
        "id": "y", "prompt": "Implement foo. Signature: def foo(x): ...",
        "max_score": 5, "difficulty": 2, "tags": {"primary": "python", "secondary": []},
    }
    targets = score_targets(legacy)
    assert len(targets) == 1
    assert targets[0]["key"] == "foo"
    assert targets[0]["max_score"] == 5


def test_answer_for_task(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "af.db")
    from coach.steps import answer_for_task, insert_step

    insert_step(
        "s", "c", 0, {"id": "t"}, "bank", "code-here", 5, 5, 1.0, 1.0, [],
        None, None, {}, None,
    )
    assert answer_for_task("s", "t") == "code-here"
    assert answer_for_task("s", "nope") is None