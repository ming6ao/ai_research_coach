"""Hierarchical mastery estimator tests (coach.area_score).

Covers order-invariance, read-time empirical-Bayes shrinkage (sparse skills
report ~ area estimate, dense skills converge to own evidence, unattempted
skills report the area estimate), and that only the primary skill feeds
beliefs.
"""

from __future__ import annotations

import random

import pytest

from coach.area_score import (
    ETA,
    AreaState,
    area_report_dict,
    fold_reported,
    reported,
    weight,
)
from coach.score import INITIAL_SCORE, INITIAL_VARIANCE
from coach.taxonomy import ALL_NODES, DOMAINS


def test_weight_extremes():
    assert weight(0) == 0.0
    assert weight(10 ** 6) > 0.9999  # dense evidence dominates
    assert weight(ETA) == 0.5


def test_update_increments_count_and_moves_mean():
    st = AreaState()
    st2 = st.update(2, 0.9)
    assert st2.questions_answered == 1
    assert st2.mean > INITIAL_SCORE
    assert st2.variance < INITIAL_VARIANCE
    # Original state is immutable.
    assert st.questions_answered == 0


def test_order_invariance_same_multiset():
    pairs = [(2, 0.52), (2, 0.55), (2, 0.57), (2, 0.53), (2, 0.56), (2, 0.54)]
    a = AreaState()
    for diff, obs in pairs:
        a = a.update(diff, obs)
    b = AreaState()
    for diff, obs in reversed(pairs):
        b = b.update(diff, obs)
    c = AreaState()
    for diff, obs in random.Random(7).sample(pairs, len(pairs)):
        c = c.update(diff, obs)
    assert a.mean == pytest.approx(b.mean, abs=1e-12) == pytest.approx(c.mean, abs=1e-12)
    assert a.variance == pytest.approx(b.variance, abs=1e-12) == pytest.approx(c.variance, abs=1e-12)
    assert a.questions_answered == b.questions_answered == c.questions_answered


def test_unattempted_reports_parent_estimate():
    # n=0 -> w=0 -> reported == parent's shrunk estimate exactly.
    parent = AreaState(mean=0.7, variance=0.04, questions_answered=10)
    child = AreaState()
    mu, var = reported(child, parent.mean, parent.variance)
    assert mu == parent.mean
    assert var == parent.variance


def test_sparse_skill_reports_mostly_area():
    area = AreaState(mean=0.7, variance=0.02, questions_answered=9)
    skill = AreaState().update(2, 0.9)
    mu, _ = reported(skill, area.mean, area.variance)
    w = weight(skill.questions_answered)
    expected = w * skill.mean + (1 - w) * area.mean
    assert abs(mu - expected) < 1e-12
    assert abs(mu - area.mean) < abs(mu - skill.mean)


def test_dense_skill_converges_to_own_mean():
    area = AreaState(mean=0.5, variance=0.02, questions_answered=100)
    skill = AreaState()
    for _ in range(200):
        skill = skill.update(2, 0.95)
    mu, _ = reported(skill, area.mean, area.variance)
    assert abs(mu - skill.mean) < 0.02
    assert mu > 0.9


def test_fold_reported_hierarchy():
    g = AreaState().update(2, 0.8)
    area = AreaState().update(2, 0.75)
    skill = AreaState().update(2, 0.7)
    (g_mu, g_var), reports = fold_reported(
        g, {"reinforcement_learning": area, "grpo": skill}
    )
    assert g_mu == g.mean  # top of hierarchy: own statistics
    assert "reinforcement_learning" in reports
    assert "grpo" in reports
    # Unattempted skill reports its area's shrunk estimate.
    (_, _), reports2 = fold_reported(g, {"reinforcement_learning": AreaState()})
    area_mu, area_var = reports2["reinforcement_learning"]
    # eval is an unattempted area -> reports global.
    assert reports2["evaluation"][0] == g_mu


def test_area_report_dict_has_all_levels():
    g = AreaState().update(2, 0.7)
    area = AreaState().update(2, 0.65)
    skill = AreaState().update(2, 0.6)
    mastery = area_report_dict(
        g, {"reinforcement_learning": area, "grpo": skill}
    )
    assert mastery["global"]["questions_answered"] == 1
    assert set(mastery["domains"]) == set(DOMAINS)
    assert set(mastery["nodes"]) == set(ALL_NODES)
    rl = mastery["domains"]["research"]["areas"]["reinforcement_learning"]
    assert rl["skills"]["grpo"]["questions_answered"] == 1
    # Unattempted skill reports its area's shrunk score, never a blank bar.
    assert rl["skills"]["ppo"]["questions_answered"] == 0
    assert rl["skills"]["ppo"]["score"] == pytest.approx(rl["score"])


def test_eta_sanity_synthetic():
    area = AreaState(mean=0.5, variance=0.02, questions_answered=100)
    skill = AreaState().update(2, 1.0).update(2, 1.0)
    mu2, _ = reported(skill, area.mean, area.variance)
    assert abs(mu2 - (0.5 * skill.mean + 0.5 * area.mean)) < 1e-9

    dense = AreaState()
    for _ in range(20):
        dense = dense.update(2, 1.0)
    mu20, _ = reported(dense, area.mean, area.variance)
    assert mu20 > mu2


def test_only_primary_tag_updates_the_estimator():
    # One answer updates exactly the primary skill + its area + domain + global.
    # Secondary skills never feed the estimator (n stays 0).
    import tempfile, pathlib

    import coach.db as db

    tmp = pathlib.Path(tempfile.mkdtemp()) / "prim.db"
    db.DB_PATH = tmp

    import coach.judge as judge_mod

    class FakeJudge:
        def evaluate(self, task, answer, previous_code=None):
            from coach.judge import CoachContent, CoachStep, EvaluationResult, score_targets

            targets = score_targets(task)
            parts = [
                {"key": p["key"], "score": float(p["max_score"]), "rationale": "Perfect part."}
                for p in targets
            ]
            max_score = sum(int(p["max_score"]) for p in targets)
            coach = CoachContent(feedback="ok", misconception="", steps=[CoachStep("t", "e", None)])
            result = EvaluationResult(task["id"], max_score, max_score, "Perfect.", coach.to_dict(), parts)
            return result, coach

    judge_mod.LLMJudge = FakeJudge
    from coach.tasks import create_task
    from backend.main import app
    from fastapi.testclient import TestClient

    task = create_task(
        owner="bank@example.com", source="user", is_public=True,
        tags={"primary": "flash_attention", "secondary": ["continuous_batching"]},
        parts=[{"key": "solution", "prompt": "Implement flash attention.",
                "tags": {"primary": "flash_attention", "secondary": ["continuous_batching"]},
                "max_score": 5, "difficulty": 2}],
    )
    client = TestClient(app)
    res = client.post("/api/v1/sessions", json={"task_ids": [task["id"]]})
    sid = res.json()["data"]["id"]
    data = client.post(
        f"/api/v1/sessions/{sid}/answers",
        json={"task_id": task["id"], "answer": "def f():\n    pass\n"},
    ).json()["data"]
    m = data["mastery"]
    nodes = m["nodes"]
    assert nodes["flash_attention"]["questions_answered"] == 1
    assert nodes["continuous_batching"]["questions_answered"] == 0  # secondary only
    assert nodes["kernels_and_gpu"]["questions_answered"] == 1
    assert nodes["systems"]["questions_answered"] == 1
    assert m["global"]["questions_answered"] == 1
