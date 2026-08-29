"""Bayesian ability estimation and hint-aware scoring.

Each skill carries a Gaussian belief theta_s ~ N(mu, variance) over the
candidate's mastery on [0, 1]. After each task we observe an effective score
(raw judge fraction minus a penalty for viewed hints) with a
difficulty-matched measurement noise, and update with the conjugate Gaussian
formulas. All tuning constants are centralized here.

Picking "the question that gives the most information per unit of time"
reduces to maximizing the a-priori variance reduction of this belief
(see core.picker.py).
"""

import math

# --- Estimation configuration ---
# Prior: neutral mastery with wide uncertainty.
INITIAL_SCORE = 0.5
INITIAL_VARIANCE = 0.35 ** 2  # sigma_max = 0.35
SIGMA_MAX = 0.35

# Measurement noise: a well-targeted question (difficulty near the candidate's
# level) is assumed to be the most discriminating.
SIGMA_BASE = 0.18      # std-dev of a perfectly-targeted observation
KAPPA = 0.35           # extra noise per unit of difficulty mismatch

# Hints: how much a viewed hint reduces the effective score.
DEFAULT_HINT_WEIGHT = 0.15

# Backward-compatible alias (deprecated: confidence is now derived from variance).
INITIAL_CONFIDENCE = 0.0


def bayesian_update(
    mean: float,
    variance: float,
    observation: float,
    obs_variance: float,
) -> tuple[float, float]:
    """Conjugate Gaussian update.

    Args:
        mean: prior mean of the ability belief.
        variance: prior variance of the ability belief.
        observation: observed effective score (hint-adjusted), in [0, 1].
        obs_variance: measurement noise variance for this task.

    Returns:
        (posterior_mean, posterior_variance)
    """
    precision = 1.0 / variance
    obs_precision = 1.0 / obs_variance
    new_precision = precision + obs_precision
    new_mean = (precision * mean + obs_precision * observation) / new_precision
    return new_mean, 1.0 / new_precision


def expected_variance_reduction(variance: float, obs_variance: float) -> float:
    """A-priori expected information gain (posterior variance reduction).

    For a Gaussian belief the posterior variance does not depend on the
    observed value, so this is computable before the question is asked.
    """
    if obs_variance <= 0:
        return variance
    return variance ** 2 / (variance + obs_variance)


def measurement_variance(difficulty: int, ability_mean: float) -> float:
    """Noise variance of an observation of a task of `difficulty`.

    Noise is smallest when the task difficulty matches the candidate's
    estimated ability (inverse of `score_to_difficulty`) and grows linearly
    with the mismatch.
    """
    target = score_to_difficulty(ability_mean)
    sigma = SIGMA_BASE + KAPPA * abs(difficulty - target)
    return sigma * sigma


def effective_score(raw_fraction: float, hint_penalty: float) -> float:
    """Hint-adjusted score.

    Viewing hints makes a correct answer less impressive: mastery is lower
    when many hints were required. The result is clamped to [0, 1].
    """
    return max(0.0, min(1.0, raw_fraction - hint_penalty))


def confidence_from_variance(variance: float) -> float:
    """Map belief variance to a [0, 1] confidence for reports/UI."""
    return max(0.0, min(1.0, 1.0 - math.sqrt(variance) / SIGMA_MAX))


def score_to_difficulty(score: float) -> int:
    """Map mastery score to target difficulty level.

    Args:
        score: Current skill score (0.0 - 1.0)

    Returns:
        Target difficulty (1-5)
    """
    if score < 0.4:
        return 1
    elif score < 0.6:
        return 2
    elif score < 0.75:
        return 3
    elif score < 0.9:
        return 4
    else:
        return 5