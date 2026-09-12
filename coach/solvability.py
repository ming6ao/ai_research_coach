"""Solve-probability estimate used to target "similar but solvable" follow-ups.

P(solve) blends signals already in the system:

- skill belief mean (Gaussian ``SkillState.score``),
- optional node mastery / uncertainty overrides (accepted for compatibility,
  pass None to use the skill belief alone),
- task difficulty mismatch (same noise model as ``coach.score``).

Pure function, no DB access: callers pass beliefs in.
"""

from __future__ import annotations

import math

from coach.score import score_to_difficulty

TARGET_P_SOLVE = 0.80
P_SOLVE_BAND = (0.70, 0.90)


def p_solve(
    skill_mean: float,
    node_mastery: float | None = None,
    node_uncertainty: float | None = None,
    difficulty: int = 2,
    hint_penalty: float = 0.0,
) -> float:
    """Estimate probability the candidate solves a task.

    Logistic in (ability - difficulty): ability is the mean of the skill
    belief and node mastery; difficulty maps 1..5 onto the 0..1 scale.
    Uncertainty and hint load discount the estimate.
    """
    ability = max(0.0, min(1.0, skill_mean))
    if node_mastery is not None:
        ability = 0.5 * ability + 0.5 * max(0.0, min(1.0, node_mastery))
    # Difficulty 1..5 -> 0.1..0.9 anchor points.
    diff_anchor = {1: 0.15, 2: 0.35, 3: 0.55, 4: 0.75, 5: 0.9}.get(
        max(1, min(5, int(difficulty))), 0.35
    )
    logit = (ability - diff_anchor) * 6.0
    p = 1.0 / (1.0 + math.exp(-logit))
    if node_uncertainty is not None:
        p *= 1.0 - 0.25 * max(0.0, min(1.0, node_uncertainty))
    p -= hint_penalty
    return max(0.02, min(0.98, p))


def tune_difficulty_for_target(
    skill_mean: float,
    node_mastery: float | None = None,
    node_uncertainty: float | None = None,
    base_difficulty: int = 2,
    target: float = TARGET_P_SOLVE,
) -> int:
    """Pick the hardest difficulty whose P(solve) still >= target.

    Walks down from ``base_difficulty`` so successors never get harder
    than the task they follow.
    """
    for d in range(max(1, min(5, base_difficulty)), 0, -1):
        if p_solve(skill_mean, node_mastery, node_uncertainty, d) >= target:
            return d
    return 1
