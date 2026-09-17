"""Picker exploration + soft breadth guard tests."""

from __future__ import annotations

import pytest

from coach.area_score import AreaState
from coach.picker import (
    BREADTH_PENALTY,
    LAMBDA_AREA,
    LAMBDA_DOMAIN,
    LAMBDA_SKILL,
    _explore,
    _utility,
    next_task,
)
from coach.session import Session
from coach.score import expected_variance_reduction, measurement_variance


def _task(i, difficulty=2, primary="grpo", secondary=None, prompt=None):
    return {
        "id": f"t{i}",
        "difficulty": difficulty,
        "prompt": prompt or f"Implement function {i}.",
        "max_score": 5,
        "tags": {"primary": primary, "secondary": secondary or []},
    }


def _session(tasks):
    return Session("candidate", tasks=tasks)


def test_exploration_is_a_tiebreaker():
    # Two identical tasks; the one in the heavily-explored area loses to the
    # one in an unexplored area on the exploration bonus.
    session = _session(
        [
            _task(0, primary="flash_attention"),
            _task(1, primary="grpo"),
        ]
    )
    session.node_states["systems"] = AreaState(mean=0.5, variance=0.03, questions_answered=50)
    session.node_states["kernels_and_gpu"] = AreaState(
        mean=0.5, variance=0.03, questions_answered=50
    )
    session.node_states["flash_attention"] = AreaState(
        mean=0.5, variance=0.03, questions_answered=50
    )
    chosen = next_task(session)
    assert chosen["id"] == "t1"


def test_eig_dominates_for_novel_family():
    # The max exploration bonus (0.002 + 0.003 + 0.001 = 0.006) must stay well
    # below a difficulty-matched EIG term, so EIG remains the primary signal.
    session = _session([_task(0, difficulty=2)])
    eig = expected_variance_reduction(0.1225, measurement_variance(2, 0.5)) / 7.0
    assert eig > 0.010
    total_bonus = LAMBDA_DOMAIN + LAMBDA_AREA + LAMBDA_SKILL
    assert total_bonus * _explore(0) < eig


def test_utility_identical_to_baseline_when_bonuses_zeroed():
    # With saturated coverage (explore -> 0) and no previous area, utility
    # equals the plain EIG/time baseline (regression guard).
    session = _session([_task(0, difficulty=2, primary="flash_attention")])
    for node in ("systems", "kernels_and_gpu", "flash_attention"):
        session.node_states[node] = AreaState(
            mean=0.5, variance=0.03, questions_answered=10 ** 6
        )
    task = _task(0, difficulty=2, primary="flash_attention")
    utility = _utility(task, session)
    eig = expected_variance_reduction(0.1225, measurement_variance(2, 0.5))
    from coach.picker import expected_time

    assert utility == pytest.approx(eig / expected_time(task))


def test_soft_breadth_penalty_never_blocks_only_option():
    session = _session([_task(0, primary="grpo"), _task(1, primary="grpo")])
    first = next_task(session)
    assert first is not None
    session.asked_task_ids.add(first["id"])
    remaining = next_task(session)
    assert remaining is not None
    assert remaining["id"] != first["id"]


def test_breadth_penalty_applied_to_same_area():
    session = _session([_task(0, primary="grpo"), _task(1, primary="grpo")])
    task = _task(0, primary="grpo")
    # Simulate a previous same-area task.
    session.asked_task_ids.add("prev")
    session.tasks.append({"id": "prev", "difficulty": 2, "prompt": "prev.",
                          "tags": {"primary": "ppo", "secondary": []}})
    base = _utility(task, session)
    session2 = _session([_task(0, primary="grpo"), _task(1, primary="grpo")])
    base2 = _utility(task, session2)
    assert base == pytest.approx(base2 - BREADTH_PENALTY)


def test_explore_decays_with_attempts():
    assert _explore(0) == 1.0
    assert _explore(1) < _explore(0)
    assert _explore(100) < 0.02
