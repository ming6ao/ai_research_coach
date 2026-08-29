"""Adaptive question selection algorithm.

Selects the next question based on:
1. Skill importance and current confidence
2. Difficulty matching to current competency level
3. Avoiding重复 questions
4. Termination conditions
"""

from typing import Optional

from core.session import Session, SkillState
from core.score import score_to_difficulty


# Termination configuration
MAX_QUESTIONS = 25
MIN_QUESTIONS = 15
CONFIDENCE_THRESHOLD = 0.7
COVERAGE_TARGET = 0.8  # 80% of important skills must meet confidence threshold
IMPORTANT_SKILL_THRESHOLD = 4  # Skills with importance >= 4 are "important"


def next_task(session: Session) -> Optional[dict]:
    """Select next task based on adaptive priority scoring.

    Algorithm:
    1. Filter out already-asked tasks
    2. Check termination conditions
    3. Score each available task by priority
    4. Return highest-scoring task
    """
    # 1. Get available tasks (not yet asked)
    available = [t for t in session.tasks if t["id"] not in session.asked_task_ids]
    if not available:
        return None

    # 2. Check termination conditions
    if _should_terminate(session):
        return None

    # 3. Score each available task
    scored_tasks = []
    for task in available:
        task_score = _compute_task_score(task, session)
        scored_tasks.append((task_score, task))

    # 4. Select highest scoring task (with tie-breaking by difficulty)
    scored_tasks.sort(key=lambda x: (x[0], -x[1].get("difficulty", 1)), reverse=True)
    return scored_tasks[0][1]


def _compute_task_score(task: dict, session: Session) -> float:
    """Compute priority score for a task.

    Score = priority * difficulty_match
    where:
        priority = importance * (1 - confidence)
        difficulty_match = how well task difficulty matches current skill level
    """
    skill_id = task["skill"]
    state = session.get_skill_state(skill_id)

    # Get skill importance from role config
    importance = _get_skill_importance(skill_id, session)

    # Priority: high importance + low confidence = high priority
    priority = importance * (1 - state.confidence)

    # Difficulty match bonus
    task_difficulty = task.get("difficulty", 1)
    target_difficulty = score_to_difficulty(state.score)
    diff_distance = abs(task_difficulty - target_difficulty)
    diff_bonus = 1.0 - (diff_distance / 4.0)  # Normalize to 0-1

    # Final score: prioritize priority, with difficulty match as secondary factor
    return priority * (0.7 + 0.3 * diff_bonus)


def _get_skill_importance(skill_id: str, session: Session) -> int:
    """Get importance value for a skill from role config."""
    for skill in session.role_cfg.get("skills", []):
        if skill["id"] == skill_id:
            return skill.get("importance", 3)
    return 3  # Default importance


def _should_terminate(session: Session) -> bool:
    """Check if interview should terminate.

    Termination conditions:
    1. Maximum questions reached
    2. Minimum questions answered AND 80% of important skills have sufficient confidence
    """
    # Always stop at max questions
    if session.index >= MAX_QUESTIONS:
        return True

    # Don't terminate before minimum questions
    if session.index < MIN_QUESTIONS:
        return False

    # Check if enough important skills have sufficient confidence
    important_skills = [
        s for s in session.role_cfg.get("skills", [])
        if s.get("importance", 3) >= IMPORTANT_SKILL_THRESHOLD
    ]

    if not important_skills:
        return False

    confident_count = sum(
        1 for s in important_skills
        if session.get_skill_state(s["id"]).confidence >= CONFIDENCE_THRESHOLD
    )

    coverage = confident_count / len(important_skills)
    return coverage >= COVERAGE_TARGET
