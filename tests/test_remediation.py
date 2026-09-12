"""Tests for the judge-driven follow-up planner (no knowledge graph).

Uses a fake decomposer (no LLM) so the deterministic path is exercised, plus
direct checks of the budget guards, trigger logic, and hybrid picker.
"""

from __future__ import annotations

import uuid

from coach.remediation import RemediationPlanner, MAX_PER_SKILL, MAX_PER_SESSION
from coach.session import Session


class FakeDecomposer:
    """Records calls; returns a deterministic generated task (fallback-style)."""

    def __init__(self):
        self.calls = []

    def generate_followup_task(self, target_text, original_task, difficulty):
        self.calls.append((target_text, original_task, difficulty))
        return {
            "id": f"remed_{uuid.uuid4().hex[:10]}",
            "skill": original_task.get("skill", "general"),
            "type": "code",
            "difficulty": difficulty,
            "prompt": f"Simpler task for: {target_text}.",
            "max_score": 5,
            "hints": [],
            "generated": True,
            "target_text": target_text,
            "context_notes": "",
        }


def _session(**kwargs):
    s = Session(candidate=kwargs.pop("candidate", "alice@example.com"), **kwargs)
    return s


def _base_task(skill="ml_systems", difficulty=3):
    return {
        "id": "mi_sys_cache",
        "skill": skill,
        "type": "code",
        "difficulty": difficulty,
        "prompt": "Design a cache.",
        "max_score": 5,
    }


def _result(score=1, max_score=5):
    return type("R", (), {"score": score, "max_score": max_score})()


def _coach(misconception="", feedback=""):
    return type("C", (), {"misconception": misconception, "feedback": feedback})()


class TestPickNextTask:
    """Hybrid picker (coach.selection.pick_next_task)."""

    def test_pending_generated_task_surfaces_first(self):
        from coach.selection import pick_next_task

        session = _session(tasks=[_base_task()])
        generated = {
            "id": "remed_pending",
            "skill": "ml_systems",
            "type": "code",
            "difficulty": 2,
            "prompt": "Simpler warm-up.",
            "max_score": 5,
            "hints": [],
            "generated": True,
            "target_text": "confused eviction with invalidation",
        }
        session.add_generated_task(generated)
        picked = pick_next_task(session.candidate, session)
        assert picked is not None
        assert picked["id"] == "remed_pending"
        assert picked["remediation"]["focus"] == "confused eviction with invalidation"

    def test_bank_picker_fallback(self):
        from coach.selection import pick_next_task

        session = _session(tasks=[_base_task()])
        picked = pick_next_task(session.candidate, session)
        assert picked is not None
        assert picked["id"] == "mi_sys_cache"

    def test_done_when_bank_exhausted(self):
        from coach.selection import pick_next_task

        session = _session(tasks=[_base_task()])
        session.asked_task_ids.add("mi_sys_cache")
        assert pick_next_task(session.candidate, session) is None


class TestTrigger:
    def test_incorrect_answer_triggers(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        gen = planner.decide(_session(), _base_task(), _result(1, 5), _coach("gap", "fb"))
        assert gen is not None
        assert gen["generated"] is True
        assert gen["target_text"] == "gap"
        assert gen["difficulty"] <= _base_task()["difficulty"]

    def test_partially_correct_triggers(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        gen = planner.decide(_session(), _base_task(), _result(2, 5), _coach("", "weak loop"))
        assert gen is not None

    def test_correct_without_gap_does_not_trigger(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        gen = planner.decide(_session(), _base_task(), _result(5, 5), _coach("", ""))
        assert gen is None

    def test_named_gap_triggers_even_on_correct(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        gen = planner.decide(
            _session(), _base_task(), _result(5, 5),
            _coach("Confused eviction with invalidation", "Solid otherwise."),
        )
        assert gen is not None
        assert gen["target_text"] == "Confused eviction with invalidation"
        # Consolidation repetition never gets harder than the original.
        assert gen["difficulty"] <= _base_task()["difficulty"]

    def test_feedback_only_gap_triggers(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer)
        gen = planner.decide(_session(), _base_task(), _result(1, 5), _coach("", "Off-by-one in loop"))
        assert gen is not None
        assert decomposer.calls[-1][0] == "Off-by-one in loop"


class TestBudgetGuards:
    def test_per_skill_cap(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer, max_per_skill=1, max_per_session=10)
        session = _session()
        for _ in range(2):
            gen = planner.decide(session, _base_task(), _result(1, 5), _coach("gap"))
            if gen is not None:
                session.add_generated_task(gen)
        # Only one generated task for this skill despite two opportunities.
        assert sum(1 for t in session.tasks if t.get("generated")) == 1
        assert len(decomposer.calls) == 1  # second call was refused before generating

    def test_per_session_cap(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer, max_per_skill=10, max_per_session=1)
        session = _session()
        gen = planner.decide(session, _base_task(), _result(1, 5), _coach("gap"))
        assert gen is not None
        session.add_generated_task(gen)
        # Second attempt blocked by session cap.
        assert planner.decide(session, _base_task(), _result(1, 5), _coach("gap")) is None

    def test_followup_persists_to_task_bank(self, tmp_path, monkeypatch):
        import coach.db as db

        monkeypatch.setattr(db, "DB_PATH", tmp_path / "remed.db")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        from coach.remediation import plan_followup

        session = _session()
        session.tasks = [_base_task()]
        gen = plan_followup(session, _base_task(), _result(1, 5), _coach("eviction gap"))
        assert gen is not None
        assert gen in session.tasks
        from coach.tasks import get_task

        stored = get_task(gen["id"])
        assert stored is not None
        assert stored["target_text"] == "eviction gap"
        assert stored["parent_task_id"] == "mi_sys_cache"
