"""Information-efficient adaptive question selection.

Selects the next question to maximize expected information gain (posterior
variance reduction of the per-skill ability belief) per unit of expected
assessment time, weighted by skill importance and skill coverage.

Termination balances a hard question/time cap against pinning down every
important skill's ability estimate.
"""

from typing import Optional

from core.session import Session
from core.score import expected_variance_reduction, measurement_variance


# Termination configuration
MAX_QUESTIONS = 25
MIN_QUESTIONS = 15
IMPORTANT_SKILL_THRESHOLD = 4
VARIANCE_TOLERANCE = 0.01  # sigma ~ 0.1 => ability estimate is effectively pinned

DEFAULT_MAX_TIME_MIN = 45.0

# Static expected-time model (minutes) used as the cost of a question.
TIME_BASE_MIN = 4.0
TIME_PER_DIFFICULTY = 1.2
TIME_PER_100_WORDS = 1.0
TIME_NO_SCAFFOLD_EXTRA = 0.5

# Coverage boost applied to skills that have never been probed, so every
# important skill is measured instead of only the cheapest/earliest ones.
COVERAGE_BONUS = 3.0


def next_task(session: Session) -> Optional[dict]:
    """Select next task maximizing expected information gain per unit time."""
    available = [t for t in session.tasks if t["id"] not in session.asked_task_ids]
    if not available:
        return None

    if _should_terminate(session):
        return None

    scored = sorted(
        ((_utility(t, session), t) for t in available),
        key=lambda x: x[0],
        reverse=True,
    )
    return scored[0][1]


def _utility(task: dict, session: Session) -> float:
    """Utility = (expected variance reduction * importance * coverage) / cost."""
    skill_id = task["skill"]
    state = session.get_skill_state(skill_id)
    importance = _get_skill_importance(skill_id, session)

    obs_variance = measurement_variance(task.get("difficulty", 1), state.score)
    information = expected_variance_reduction(state.variance, obs_variance)

    coverage = COVERAGE_BONUS if state.questions_answered == 0 else 1.0
    cost = expected_time(task)

    return (information * importance * coverage) / cost


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


def _get_skill_importance(skill_id: str, session: Session) -> int:
    """Get importance value for a skill from role config."""
    for skill in session.role_cfg.get("skills", []):
        if skill["id"] == skill_id:
            return skill.get("importance", 3)
    return 3  # Default importance


def _elapsed_time(session: Session) -> float:
    """Sum of expected times for the tasks already administered."""
    return sum(
        expected_time(t) for t in session.tasks if t["id"] in session.asked_task_ids
    )


def _max_time_min(session: Session) -> float:
    return float(session.role_cfg.get("max_time_min", DEFAULT_MAX_TIME_MIN))


def _should_terminate(session: Session) -> bool:
    """Check whether the assessment should stop.

    Termination conditions:
    1. Maximum questions reached
    2. Expected time budget exhausted
    3. Minimum questions answered AND every important skill's ability is pinned
    """
    if session.index >= MAX_QUESTIONS:
        return True

    if _elapsed_time(session) >= _max_time_min(session):
        return True

    if session.index < MIN_QUESTIONS:
        return False

    important_skills = [
        s for s in session.role_cfg.get("skills", [])
        if s.get("importance", 3) >= IMPORTANT_SKILL_THRESHOLD
    ]
    if not important_skills:
        return False

    return all(
        session.get_skill_state(s["id"]).variance < VARIANCE_TOLERANCE
        for s in important_skills
    )