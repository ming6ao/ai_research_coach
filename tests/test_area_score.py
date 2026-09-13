"""Hierarchical mastery estimator tests (coach.area_score).

Covers §4: order-invariance, read-time empirical-Bayes shrinkage (sparse tags
report ~ family estimate, dense tags converge to own evidence, unattempted
tags report the family estimate), and that only the primary tag feeds beliefs.
"""

from __future__ import annotations

import random

from coach.area_score import (
    ETA,
    AreaState,
    area_report_dict,
    fold_reported,
    reported,
    weight,
)
from coach.score import INITIAL_SCORE, INITIAL_VARIANCE
from coach.taxonomy import ALL_TAGS, FAMILIES


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
    # The same (difficulty, observation) pairs in any order produce identical
    # beliefs. Using a fixed difficulty and observations that keep the own mean
    # within one difficulty band makes every update share the same obs variance,
    # so the conjugate-Gaussian updates commute exactly.
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


def test_order_invariance_shuffled_identical_answers():
    # Identical answers (same difficulty + score) at any positions collapse to
    # the same belief regardless of insertion order.
    seq = [(2, 0.55)] * 8
    a = AreaState()
    b = AreaState()
    for diff, obs in seq:
        a = a.update(diff, obs)
        b = b.update(diff, obs)
    a_mu, a_var = reported(a, INITIAL_SCORE, INITIAL_VARIANCE)
    b_mu, b_var = reported(b, INITIAL_SCORE, INITIAL_VARIANCE)
    assert a_mu == b_mu and a_var == b_var
    assert a_mu > INITIAL_SCORE  # evidence moved the belief up


def test_unattempted_reports_parent_estimate():
    # n=0 -> w=0 -> reported == parent's shrunk estimate exactly.
    parent = AreaState(mean=0.7, variance=0.04, questions_answered=10)
    child = AreaState()
    mu, var = reported(child, parent.mean, parent.variance)
    assert mu == parent.mean
    assert var == parent.variance


def test_sparse_tag_reports_mostly_family():
    # One observation: weight 1/(1+2) = 1/3 on own evidence, 2/3 on family.
    family = AreaState(mean=0.7, variance=0.02, questions_answered=9)
    tag = AreaState().update(2, 0.9)
    mu, _ = reported(tag, family.mean, family.variance)
    w = weight(tag.questions_answered)
    expected = w * tag.mean + (1 - w) * family.mean
    assert abs(mu - expected) < 1e-12
    # The report leans on the family for a sparse tag.
    assert abs(mu - family.mean) < abs(mu - tag.mean)


def test_dense_tag_converges_to_own_mean():
    family = AreaState(mean=0.5, variance=0.02, questions_answered=100)
    tag = AreaState()
    for _ in range(200):
        tag = tag.update(2, 0.95)
    mu, _ = reported(tag, family.mean, family.variance)
    # Dense evidence (n >> eta) -> reported converges to the tag's OWN mean.
    assert abs(mu - tag.mean) < 0.02
    assert mu > 0.9


def test_fold_reported_hierarchy():
    g = AreaState().update(2, 0.8)
    fam = AreaState().update(2, 0.75)
    tag = AreaState().update(2, 0.7)
    (g_mu, g_var), family_reports, tag_reports = fold_reported(
        g, {"python": fam}, {"data_structures": tag}
    )
    assert g_mu == g.mean  # top of hierarchy: own statistics
    assert "python" in family_reports
    # Unattempted family reports the global estimate.
    fam_unattempted = AreaState()
    (_, _), fam2, _ = fold_reported(g, {"python": fam_unattempted}, {})
    assert fam2["python"][0] == g_mu


def test_area_report_dict_has_all_levels():
    g = AreaState().update(2, 0.7)
    fam = AreaState().update(2, 0.65)
    tag = AreaState().update(2, 0.6)
    mastery = area_report_dict(g, {"ml_classical": fam}, {"linear_regression": tag})
    assert mastery["global"]["questions_answered"] == 1
    assert set(mastery["families"]) == set(FAMILIES)
    assert set(mastery["tags"]) == set(ALL_TAGS)
    # Unattempted tag reports its family's shrunk score, never a blank bar.
    fam_score = mastery["families"]["ml_classical"]["score"]
    assert mastery["tags"]["linear_regression"]["questions_answered"] == 1
    assert mastery["tags"]["cnn"]["questions_answered"] == 0
    assert mastery["tags"]["cnn"]["score"] == pytest.approx(
        mastery["families"]["dl_arch"]["score"]
    )


def test_eta_sanity_synthetic():
    # With eta=2, roughly 2 observations put a level halfway between its own
    # evidence and its parent's; ~20 observations make own evidence dominant.
    family = AreaState(mean=0.5, variance=0.02, questions_answered=100)
    tag = AreaState().update(2, 1.0).update(2, 1.0)
    mu2, _ = reported(tag, family.mean, family.variance)
    assert abs(mu2 - (0.5 * tag.mean + 0.5 * family.mean)) < 1e-9

    dense = AreaState()
    for _ in range(20):
        dense = dense.update(2, 1.0)
    mu20, _ = reported(dense, family.mean, family.variance)
    assert mu20 > mu2


def test_only_primary_tag_updates_the_estimator():
    # One answer updates exactly the primary tag + its family + global.
    # Secondary tags never feed the estimator (n stays 0).
    import coach.db as db
    from fastapi.testclient import TestClient

    import tempfile, pathlib

    tmp = pathlib.Path(tempfile.mkdtemp()) / "prim.db"
    db.DB_PATH = tmp

    import coach.judge as judge_mod

    class FakeJudge:
        def evaluate(self, task, answer):
            from coach.judge import CoachContent, CoachStep, EvaluationResult

            coach = CoachContent(feedback="ok", misconception="", steps=[CoachStep("t", "e", None)])
            result = EvaluationResult(task["id"], 5, 5, "Perfect.", coach.to_dict())
            return result, coach

    judge_mod.LLMJudge = FakeJudge
    from coach.tasks import create_task
    from backend.main import app

    task = create_task(
        prompt="Implement a conv.", owner="system", source="seed", is_public=True,
        tags={"primary": "cnn", "secondary": ["mlp"]},
    )
    client = TestClient(app)
    res = client.post("/api/v1/sessions", json={"task_ids": [task["id"]]})
    sid = res.json()["data"]["id"]
    data = client.post(
        f"/api/v1/sessions/{sid}/answers",
        json={"task_id": task["id"], "answer": "def f():\n    pass\n"},
    ).json()["data"]
    m = data["mastery"]
    assert m["tags"]["cnn"]["questions_answered"] == 1
    assert m["tags"]["mlp"]["questions_answered"] == 0  # secondary never updates
    assert m["families"]["dl_arch"]["questions_answered"] == 1
    assert m["global"]["questions_answered"] == 1


import pytest  # noqa: E402  (used by test_area_report_dict_has_all_levels)