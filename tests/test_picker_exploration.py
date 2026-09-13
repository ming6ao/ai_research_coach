"""Picker exploration + soft breadth guard tests (design doc §5)."""

from __future__ import annotations

from coach.area_score import AreaState
from coach.picker import (
    BREADTH_PENALTY,
    LAMBDA_FAMILY,
    LAMBDA_TAG,
    _explore,
    _utility,
    next_task,
)
from coach.session import Session
from coach.score import expected_variance_reduction, measurement_variance


def _task(i, difficulty=2, primary="python", secondary=None, prompt=None):
    return {
        "id": f"t{i}",
        "difficulty": difficulty,
        "prompt": prompt or f"Implement function {i}.",
        "max_score": 5,
        "tags": {"primary": primary, "secondary": secondary or []},
    }


def _session(tasks):
    s = Session("candidate", tasks=tasks)
    return s


def test_exploration_is_a_tiebreaker():
    # Two tasks with identical EIG/cost (same difficulty + prompt): the one
    # with zero coverage (max exploration) must win.
    session = _session(
        [
            _task(0, primary="python"),
            _task(1, primary="python"),
        ]
    )
    # Mark family "python" as heavily explored for task 1, but task 0 uses the
    # same family... we need distinct families to differ in exploration.
    session = _session(
        [
            _task(0, primary="python"),
            _task(1, primary="dl_arch"),
        ]
    )
    session.family_states["python"] = AreaState(mean=0.5, variance=0.03, questions_answered=50)
    session.tag_states["data_structures"] = AreaState(
        mean=0.5, variance=0.03, questions_answered=50
    )
    # Both are difficulty 2 with identical prompts, so EIG/cost is equal; the
    # less-explored dl_arch family should be picked on exploration.
    chosen = next_task(session)
    assert chosen["id"] == "t1"


def test_eig_dominates_for_novel_family():
    # The max exploration bonus (0.004 + 0.001 = 0.005) must stay well below a
    # difficulty-matched EIG term, so EIG remains the primary signal.
    session = _session([_task(0, difficulty=2)])
    utility = _utility(_task(0, difficulty=2), session)
    eig = expected_variance_reduction(0.1225, measurement_variance(2, 0.5)) / 7.0
    assert eig > 0.010
    assert LAMBDA_FAMILY * _explore(0) + LAMBDA_TAG * _explore(0) < eig


def test_utility_identical_to_baseline_when_bonuses_zeroed():
    # With saturated coverage (explore -> 0) and no previous family, utility
    # equals the plain EIG/time baseline (regression guard).
    session = _session([_task(0, difficulty=2)])
    session.family_states["python"] = AreaState(
        mean=0.5, variance=0.03, questions_answered=10 ** 6
    )
    session.tag_states["data_structures"] = AreaState(
        mean=0.5, variance=0.03, questions_answered=10 ** 6
    )
    task = _task(0, difficulty=2)
    utility = _utility(task, session)
    eig = expected_variance_reduction(0.1225, measurement_variance(2, 0.5))
    from coach.picker import expected_time

    assert utility == pytest.approx(eig / expected_time(task))


def test_soft_breadth_penalty_never_blocks_only_option():
    # When only same-family tasks remain, next_task must still return one
    # (soft penalty, never None / deadlock).
    session = _session([_task(0, primary="python"), _task(1, primary="python")])
    first = next_task(session)
    assert first is not None
    session.asked_task_ids.add(first["id"])
    remaining = next_task(session)
    assert remaining is not None
    assert remaining["id"] != first["id"]


def test_breadth_penalty_applied_to_same_family():
    session = _session([_task(0, primary="python"), _task(1, primary="python")])
    task = _task(0, primary="python")
    # Simulate a previous same-family task.
    session.asked_task_ids.add("prev")
    session.tasks.append({"id": "prev", "difficulty": 2, "prompt": "prev.",
                          "tags": {"primary": "python", "secondary": []}})
    base = _utility(task, session)
    # Same task, but no previous family in the session.
    session2 = _session([_task(0, primary="python"), _task(1, primary="python")])
    base2 = _utility(task, session2)
    assert base == pytest.approx(base2 - BREADTH_PENALTY)


def test_explore_decays_with_attempts():
    assert _explore(0) == 1.0
    assert _explore(1) < _explore(0)
    assert _explore(100) < 0.02


import pytest  # noqa: E402