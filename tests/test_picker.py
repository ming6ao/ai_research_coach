"""Unit tests for the information-efficient question picker in coach.picker."""

import pytest

from coach.picker import expected_time, next_task
from coach.session import Session

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


def test_expected_time_model():
    base = expected_time({"difficulty": 1, "prompt": "short prompt", "scaffold": "x"})
    hard = expected_time({"difficulty": 5, "prompt": "short prompt", "scaffold": "x"})
    assert hard > base
    override = expected_time({"difficulty": 1, "expected_time_min": 2.5})
    assert override == pytest.approx(2.5)


def test_unified_bank_includes_all_former_roles():
    # Explicit bank covering both skills; the picker serves any skill.
    session = make_session(
        [make_task(0, "ml_modeling"), make_task(1, "ml_systems")]
    )
    skills = {t["skill"] for t in session.tasks}
    assert "ml_modeling" in skills
    assert "ml_systems" in skills
    first = next_task(session)
    assert first is not None
    assert first["skill"] in skills