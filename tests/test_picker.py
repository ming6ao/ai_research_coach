"""Unit tests for the information-efficient question picker in coach.picker."""

from coach.picker import expected_time, next_task
from coach.session import Session


def make_task(i, difficulty=2):
    return {
        "id": f"t{i}",
        "difficulty": difficulty,
        "prompt": f"Implement function {i}.",
        "max_score": 5,
    }


def make_session(tasks):
    return Session("candidate", tasks=tasks)


def test_next_task_none_when_exhausted():
    session = make_session([make_task(0)])
    first = next_task(session)
    assert first is not None
    session.asked_task_ids.add(first["id"])
    assert next_task(session) is None


def test_next_task_prefers_matched_difficulty():
    # Ability starts at 0.5 -> target difficulty 2, so the difficulty-2 task
    # has lower measurement noise and therefore higher expected information.
    session = make_session(
        [
            make_task(0, difficulty=1),
            make_task(1, difficulty=2),
        ]
    )
    chosen = next_task(session)
    assert chosen["difficulty"] == 2


def test_next_task_prefers_cheaper_task_at_equal_information():
    # Same difficulty -> same information; the shorter prompt costs less time.
    session = make_session(
        [
            {"id": "long", "difficulty": 2, "prompt": "word " * 200, "max_score": 5},
            {"id": "short", "difficulty": 2, "prompt": "short prompt", "max_score": 5},
        ]
    )
    assert next_task(session)["id"] == "short"


def test_expected_time_model():
    base = expected_time({"difficulty": 1, "prompt": "short prompt"})
    hard = expected_time({"difficulty": 5, "prompt": "short prompt"})
    assert hard > base


def test_bank_tasks_have_no_skill():
    session = make_session([make_task(0), make_task(1)])
    first = next_task(session)
    assert first is not None
    assert "skill" not in first
