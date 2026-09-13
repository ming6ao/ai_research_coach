"""Information-efficient adaptive question selection.

Selects the next question to maximize expected information gain (posterior
variance reduction of the overall ability belief) per unit of expected
assessment time, plus small, well-calibrated exploration bonuses layered on
top so the picker widens coverage into under-explored families/tags without
ever replacing the EIG signal (design doc §5).

The session is open-ended: when the bank is exhausted, ``coach.selection``
mints a fresh adaptive challenge task instead of ending (the user exits
explicitly via Finish / View progress).
"""

from typing import Optional

import random

from coach.session import Session
from coach.score import expected_variance_reduction, measurement_variance
from coach.taxonomy import FAMILIES, family_of


# Static expected-time model (minutes) used as the cost of a question.
TIME_BASE_MIN = 4.0
TIME_PER_DIFFICULTY = 1.2
TIME_PER_100_WORDS = 1.0
TIME_NO_SCAFFOLD_EXTRA = 0.5

# Exploration weights (unit-consistent with EIG_global/time ~ 0.005-0.015).
# They must stay well below the EIG term so exploration is a genuine
# tiebreaker, never a replacement (§5).
LAMBDA_FAMILY = 0.004
LAMBDA_TAG = 0.001

# Soft breadth penalty: applied to a candidate task whose primary family
# equals the previously asked task's family. Soft, so it can never remove
# the last viable bank task (no deadlock).
BREADTH_PENALTY = 0.010


def next_task(session: Session, sample_top_n: Optional[int] = None) -> Optional[dict]:
    """Select next task maximizing expected information gain per unit time.

    Generated remediation tasks are excluded: they are injected directly by the
    remediation loop, never picked from the bank.

    When ``sample_top_n`` is set (> 1), uniformly sample from the top-N
    highest-utility tasks instead of always returning the single best. This
    keeps the "Random question" entry point varied while staying adaptive.
    """
    available = [
        t for t in session.tasks
        if t["id"] not in session.asked_task_ids and not t.get("generated")
    ]
    if not available:
        return None

    scored = sorted(
        ((_utility(t, session), t) for t in available),
        key=lambda x: x[0],
        reverse=True,
    )
    if sample_top_n is not None and sample_top_n > 1:
        top_n = scored[: max(1, min(sample_top_n, len(scored)))]
        return random.choice([t for _, t in top_n])
    return scored[0][1]


def _explore(attempts: int) -> float:
    """Exploration bonus for a family/tag with `attempts` observations."""
    return 1.0 / (1.0 + max(0, int(attempts)))


def _utility(task: dict, session: Session) -> float:
    """Utility = EIG/time + exploration bonuses - soft breadth penalty."""
    state = session.get_ability()

    obs_variance = measurement_variance(task.get("difficulty", 1), state.score)
    information = expected_variance_reduction(state.variance, obs_variance)

    cost = expected_time(task)

    eig = information / cost

    tags = task.get("tags") or {}
    primary = tags.get("primary")
    fam = family_of(primary)

    explore = 0.0
    if fam:
        explore += LAMBDA_FAMILY * _explore(
            session.get_family_state(fam).questions_answered
        )
    # Only real fine tags feed the tag-level term; a family used as the
    # primary (fallback "python") already counts via the family term.
    if primary and primary not in FAMILIES:
        explore += LAMBDA_TAG * _explore(
            session.get_tag_state(primary).questions_answered
        )

    utility = eig + explore

    prev_fam = session.previous_family()
    if fam and prev_fam and fam == prev_fam:
        utility -= BREADTH_PENALTY

    return utility


def expected_time(task: dict) -> float:
    """Expected minutes to complete a task (static prior)."""
    prompt_words = len(task.get("prompt", "").split())
    minutes = (
        TIME_BASE_MIN
        + TIME_PER_DIFFICULTY * task.get("difficulty", 1)
        + TIME_PER_100_WORDS * prompt_words / 100.0
    )
    if not task.get("scaffold"):
        minutes += TIME_NO_SCAFFOLD_EXTRA
    return minutes
