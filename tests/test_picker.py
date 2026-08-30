"""Unit tests for the information-efficient question picker in core.picker."""

import pytest

from core.picker import _should_terminate, expected_time, next_task
from core.session import Session

SKILLS = [
    "ml_modeling",
    "ml_systems",
]


def make_task(i, skill, difficulty=2):
    return {
        "id": f"t{i}",
        "skill": skill,
        "difficulty": difficulty,
        "prompt": f"Implement function {i}.",
        "max_score": 5,
    }


def make_session(tasks):
    return Session("candidate", tasks=tasks)


def test_next_task_none_when_exhausted():
    session = make_session([make_task(0, "ml_fundamentals")])
    first = next_task(session)
    assert first is not None
    session.asked_task_ids.add(first["id"])
    assert next_task(session) is None


def test_next_task_prefers_matched_difficulty():
    # Ability starts at 0.5 -> target difficulty 2, so the difficulty-2 task
    # has lower measurement noise and therefore higher expected information.
    session = make_session(
        [
            make_task(0, "ml_fundamentals", difficulty=1),
            make_task(1, "ml_fundamentals", difficulty=2),
        ]
    )
    chosen = next_task(session)
    assert chosen["difficulty"] == 2


def test_probes_all_skills_before_revisiting():
    tasks = [make_task(i, skill) for i, skill in enumerate(SKILLS)]
    session = make_session(tasks)
    session.max_time_min = 1000.0  # keep the 45-min budget from truncating the probe
    seen_skills = []
    for _ in range(len(tasks)):
        task = next_task(session)
        assert task is not None
        seen_skills.append(task["skill"])
        # Simulate a highly informative answer that pins the skill down.
        state = session.get_skill_state(task["skill"])
        state.variance = 0.0001
        state.questions_answered += 1
        session.asked_task_ids.add(task["id"])
    assert len(set(seen_skills)) == len(SKILLS)


def test_time_budget_terminates():
    session = make_session([make_task(0, "ml_fundamentals"), make_task(1, "deep_learning")])
    session.max_time_min = 0.0
    assert next_task(session) is None


def test_early_termination_when_important_skills_pinned():
    session = make_session([make_task(0, "ml_fundamentals"), make_task(1, "deep_learning")])
    session.index = 15
    for skill in SKILLS:
        session.get_skill_state(skill).variance = 0.0001
    assert _should_terminate(session) is True


def test_no_early_termination_below_min_questions():
    session = make_session([make_task(0, "ml_fundamentals")])
    session.index = 5
    for skill in SKILLS:
        session.get_skill_state(skill).variance = 0.0001
    assert _should_terminate(session) is False


def test_expected_time_model():
    base = expected_time({"difficulty": 1, "prompt": "short prompt", "scaffold": "x"})
    hard = expected_time({"difficulty": 5, "prompt": "short prompt", "scaffold": "x"})
    assert hard > base
    override = expected_time({"difficulty": 1, "expected_time_min": 2.5})
    assert override == pytest.approx(2.5)


def test_unified_bank_includes_all_former_roles():
    # A fresh session loads every task (no role filter), so tasks from both
    # former role trees are eligible for any candidate.
    session = Session("candidate")
    skills = {t["skill"] for t in session.tasks}
    assert len(session.tasks) == 30
    assert "ml_modeling" in skills
    assert "ml_systems" in skills
    # The picker can choose from any former role in one pass.
    session.max_time_min = 0.0  # force selection (no termination yet)
    first = next_task(Session("candidate"))
    second = next_task(session)
    assert first is not None and second is None