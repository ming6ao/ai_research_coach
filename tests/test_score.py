"""Unit tests for the Bayesian ability estimation in core.score."""

import pytest

from core.score import (
    INITIAL_SCORE,
    INITIAL_VARIANCE,
    bayesian_update,
    confidence_from_variance,
    effective_score,
    expected_variance_reduction,
    measurement_variance,
    score_to_difficulty,
)


def test_effective_score_without_hints_preserves_raw():
    assert effective_score(0.8, 0.0) == pytest.approx(0.8)


def test_effective_score_discounts_hints():
    assert effective_score(1.0, 0.5) == pytest.approx(0.5)
    assert effective_score(0.8, 0.2) == pytest.approx(0.6)


def test_effective_score_clamps_to_range():
    assert effective_score(0.3, 0.5) == pytest.approx(0.0)
    assert effective_score(1.1, 0.0) == pytest.approx(1.0)


def test_measurement_variance_prefers_matched_difficulty():
    ability = 0.5  # score_to_difficulty(0.5) == 2
    matched = measurement_variance(2, ability)
    nearby = measurement_variance(3, ability)
    far = measurement_variance(5, ability)
    assert matched < nearby < far
    assert matched > 0


def test_bayesian_update_shrinks_variance():
    mean, variance = bayesian_update(INITIAL_SCORE, INITIAL_VARIANCE, 1.0, 0.03)
    assert variance < INITIAL_VARIANCE
    assert mean > INITIAL_SCORE


def test_bayesian_update_converges_to_true_ability():
    # Repeated strong observations should drive the mean toward the observation.
    mean, variance = INITIAL_SCORE, INITIAL_VARIANCE
    for _ in range(20):
        mean, variance = bayesian_update(mean, variance, 0.95, 0.03)
    assert mean == pytest.approx(0.95, abs=0.01)
    assert variance < 0.01


def test_bayesian_update_high_noise_changes_little():
    mean, variance = bayesian_update(INITIAL_SCORE, INITIAL_VARIANCE, 0.0, 100.0)
    assert mean == pytest.approx(INITIAL_SCORE, abs=0.05)
    assert variance == pytest.approx(INITIAL_VARIANCE, abs=0.05)


def test_expected_variance_reduction_matches_posterior():
    prior_var = 0.1225
    obs_var = 0.03
    eig = expected_variance_reduction(prior_var, obs_var)
    _, post_var = bayesian_update(0.5, prior_var, 0.7, obs_var)
    assert eig == pytest.approx(prior_var - post_var)


def test_expected_variance_reduction_increases_with_uncertainty():
    assert expected_variance_reduction(0.2, 0.05) > expected_variance_reduction(0.05, 0.05)


def test_expected_variance_reduction_decreases_with_noise():
    assert expected_variance_reduction(0.2, 0.05) > expected_variance_reduction(0.2, 5.0)


def test_confidence_starts_zero_and_rises():
    assert confidence_from_variance(INITIAL_VARIANCE) == pytest.approx(0.0)
    assert confidence_from_variance(0.0001) > 0.9
    assert confidence_from_variance(1.0) == 0.0


def test_score_to_difficulty_monotonic():
    assert score_to_difficulty(0.2) == 1
    assert score_to_difficulty(0.5) == 2
    assert score_to_difficulty(0.95) == 5