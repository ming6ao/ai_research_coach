"""Information-efficient adaptive question selection.

Selects the next question to maximize expected information gain (posterior
variance reduction of the per-skill ability belief) per unit of expected
assessment time, weighted by skill coverage.

The assessment ends when the question bank is exhausted.
"""

from typing import Optional

from core.session import Session
from core.score import expected_variance_reduction, measurement_variance


# Static expected-time model (minutes) used as the cost of a question.
TIME_BASE_MIN = 4.0
TIME_PER_DIFFICULTY = 1.2
TIME_PER_100_WORDS = 1.0
TIME_NO_SCAFFOLD_EXTRA = 0.5

# Coverage boost applied to skills that have never been probed, so every
# skill in the bank is measured instead of only the cheapest/earliest ones.
COVERAGE_BONUS = 3.0


def next_task(session: Session) -> Optional[dict]:
    """Select next task maximizing expected information gain per unit time.

    Generated remediation tasks are excluded: they are injected directly by the
    remediation loop, never picked from the bank.
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
    return scored[0][1]


def _utility(task: dict, session: Session) -> float:
    """Utility = (expected variance reduction * coverage) / cost."""
    skill_id = task["skill"]
    state = session.get_skill_state(skill_id)

    obs_variance = measurement_variance(task.get("difficulty", 1), state.score)
    information = expected_variance_reduction(state.variance, obs_variance)

    coverage = COVERAGE_BONUS if state.questions_answered == 0 else 1.0
    cost = expected_time(task)

    return (information * coverage) / cost


def expected_time(task: dict) -> float:
    """Expected minutes to complete a task (static prior).

    A task can override the model with an explicit `expected_time_min`.
    """
    override = task.get("expected_time_min")
    if override:
        return float(override)

    prompt_words = len(task.get("prompt", "").split())
    minutes = (
        TIME_BASE_MIN
        + TIME_PER_DIFFICULTY * task.get("difficulty", 1)
        + TIME_PER_100_WORDS * prompt_words / 100.0
    )
    if not task.get("scaffold"):
        minutes += TIME_NO_SCAFFOLD_EXTRA
    return minutes
