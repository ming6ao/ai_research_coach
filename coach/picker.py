"""Information-efficient adaptive question selection.

Selects the next question to maximize expected information gain (posterior
variance reduction of the overall ability belief) per unit of expected
assessment time.

The session is open-ended: when the bank is exhausted, ``coach.selection``
mints a fresh adaptive challenge task instead of ending (the user exits
explicitly via Finish / View progress).
"""

from typing import Optional

import random

from coach.session import Session
from coach.score import expected_variance_reduction, measurement_variance


# Static expected-time model (minutes) used as the cost of a question.
TIME_BASE_MIN = 4.0
TIME_PER_DIFFICULTY = 1.2
TIME_PER_100_WORDS = 1.0
TIME_NO_SCAFFOLD_EXTRA = 0.5


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


def _utility(task: dict, session: Session) -> float:
    """Utility = expected variance reduction / cost."""
    state = session.get_ability()

    obs_variance = measurement_variance(task.get("difficulty", 1), state.score)
    information = expected_variance_reduction(state.variance, obs_variance)

    cost = expected_time(task)

    return information / cost


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
