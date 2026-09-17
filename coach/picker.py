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
from coach.taxonomy import (
    NODE_LEVEL,
    ancestors,
    area_of,
    domain_of,
    resolve_node,
)


# Static expected-time model (minutes) used as the cost of a question.
TIME_BASE_MIN = 4.0
TIME_PER_DIFFICULTY = 1.2
TIME_PER_100_WORDS = 1.0
TIME_NO_SCAFFOLD_EXTRA = 0.5

# Exploration weights (unit-consistent with EIG_global/time ~ 0.005-0.015).
# They must stay well below the EIG term so exploration is a genuine
# tiebreaker, never a replacement. One small bonus per hierarchy level.
LAMBDA_DOMAIN = 0.002
LAMBDA_AREA = 0.003
LAMBDA_SKILL = 0.001

# Soft breadth penalty: applied to a candidate task whose primary area equals
# the previously asked task's area. Soft, so it can never remove the last
# viable bank task (no deadlock).
BREADTH_PENALTY = 0.010


def next_task(
    session: Session,
    sample_top_n: Optional[int] = None,
    node: Optional[str] = None,
    family: Optional[str] = None,
) -> Optional[dict]:
    """Select next task maximizing expected information gain per unit time.

    Generated remediation tasks are excluded: they are injected directly by the
    remediation loop, never picked from the bank.

    When ``sample_top_n`` is set (> 1), uniformly sample from the top-N
    highest-utility tasks instead of always returning the single best. This
    keeps the "Random question" entry point varied while staying adaptive.

    When ``node`` (or the legacy ``family`` alias) is set, only bank tasks
    whose primary skill is that node or has it as an ancestor are eligible
    (used to seed a session with a question from an area).
    """
    available = [
        t for t in session.tasks
        if t["id"] not in session.asked_task_ids
        and not t.get("generated")
        and not t.get("depends_on_task_id")
    ]
    target = resolve_node(node or family)
    if target:
        available = [
            t for t in available if _matches_node((t.get("tags") or {}).get("primary"), target)
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


def _matches_node(primary: Optional[str], target: str) -> bool:
    """True when ``primary`` is ``target`` or is descended from it."""
    canon = resolve_node(primary)
    if canon is None:
        return False
    if canon == target:
        return True
    return target in ancestors(canon)


def _explore(attempts: int) -> float:
    """Exploration bonus for a node with `attempts` observations."""
    return 1.0 / (1.0 + max(0, int(attempts)))


def _utility(task: dict, session: Session) -> float:
    """Utility = EIG/time + per-level exploration bonuses - breadth penalty."""
    state = session.get_ability()

    obs_variance = measurement_variance(task.get("difficulty", 1), state.score)
    information = expected_variance_reduction(state.variance, obs_variance)

    cost = expected_time(task)

    eig = information / cost

    tags = task.get("tags") or {}
    primary = tags.get("primary")
    if not primary:
        return eig

    domain = domain_of(primary)
    area = area_of(primary)

    explore = 0.0
    if domain:
        explore += LAMBDA_DOMAIN * _explore(
            session.get_node_state(domain).questions_answered
        )
    if area:
        explore += LAMBDA_AREA * _explore(
            session.get_node_state(area).questions_answered
        )
    if primary and NODE_LEVEL.get(primary, 0) == 3:
        explore += LAMBDA_SKILL * _explore(
            session.get_node_state(primary).questions_answered
        )

    utility = eig + explore

    prev_area = session.previous_area()
    if area and prev_area and area == prev_area:
        utility -= BREADTH_PENALTY

    return utility


def expected_time(task: dict) -> float:
    """Expected minutes to complete a task (static prior).

    Code blocks scale linearly with their number of parts: an N-part block
    costs about N single-question tasks.
    """
    prompt_words = len(task.get("prompt", "").split())
    minutes = (
        TIME_BASE_MIN
        + TIME_PER_DIFFICULTY * task.get("difficulty", 1)
        + TIME_PER_100_WORDS * prompt_words / 100.0
    )
    if not task.get("scaffold"):
        minutes += TIME_NO_SCAFFOLD_EXTRA
    parts = task.get("parts") or []
    if parts:
        minutes *= max(1, len(parts))
    return minutes
