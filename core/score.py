"""Score update formulas and configuration constants.

All scoring constants are centralized here for easy modification.
"""

# --- Scoring Configuration ---
# Weight given to each new answer when updating skill score
SCORE_UPDATE_WEIGHT = 0.2

# How much confidence increases per question answered
CONFIDENCE_INCREMENT = 0.15

# Maximum confidence value (prevents over-certainty)
CONFIDENCE_CEILING = 0.95

# Initial score for all skills (neutral starting point)
INITIAL_SCORE = 0.5

# Initial confidence (no evidence yet)
INITIAL_CONFIDENCE = 0.0


def update_skill_score(
    current_score: float,
    current_confidence: float,
    answer_fraction: float,
) -> tuple[float, float]:
    """Update skill score using weighted average.

    Args:
        current_score: Current skill score (0.0 - 1.0)
        current_confidence: Current confidence (0.0 - 1.0)
        answer_fraction: Normalized answer score (0.0 - 1.0)

    Returns:
        Tuple of (new_score, new_confidence)
    """
    new_score = (
        current_score * current_confidence +
        answer_fraction * SCORE_UPDATE_WEIGHT
    ) / (
        current_confidence + SCORE_UPDATE_WEIGHT
    )

    new_confidence = min(CONFIDENCE_CEILING, current_confidence + CONFIDENCE_INCREMENT)

    return new_score, new_confidence


def score_to_difficulty(score: float) -> int:
    """Map competency score to target difficulty level.

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
