"""Tests for the judge-driven follow-up planner (no knowledge graph).

Uses a fake decomposer (no LLM) so the deterministic path is exercised, plus
direct checks of the budget guards, trigger logic, and hybrid picker.
"""

from __future__ import annotations

import uuid

from coach.remediation import RemediationPlanner, MAX_PER_SESSION
from coach.session import Session


class FakeDecomposer:
    """Records calls; returns a deterministic generated task (no LLM)."""

    def __init__(self):
        self.calls = []

    def generate_followup_task(self, target_text, original_task, difficulty, mode="remediate", extra_context=""):
        self.calls.append((target_text, original_task, difficulty, mode))
        prompt = f"{mode} task for: {target_text}."
        return {
            "id": f"remed_{uuid.uuid4().hex[:10]}",
            "type": "code",
            "difficulty": difficulty,
            "prompt": prompt,
            "max_score": 5,
            "hints": [],
            "parts": [
                {
                    "key": "solution",
                    "prompt": prompt,
                    "tags": (original_task or {}).get("tags") or {"primary": "caching"},
                    "max_score": 5,
                    "difficulty": difficulty,
                    "scaffold": "def solution():\n    # TODO\n    pass\n",
                }
            ],
            "generated": True,
            "generated_kind": mode,
            "target_text": target_text,
            "context_notes": "",
            "tags": (original_task or {}).get("tags") or {"primary": "caching"},
            "parent_task_id": (original_task or {}).get("id"),
            "root_task_id": (original_task or {}).get("root_task_id") or (original_task or {}).get("id"),
            "root_difficulty": (original_task or {}).get("root_difficulty", (original_task or {}).get("difficulty", 2)),
        }

    def generate_challenge_task(self, difficulty, avoid_text="", prefer_node="", tags=None):
        self.calls.append(("__challenge__", {}, difficulty, "challenge"))
        prompt = "Fresh challenge task."
        return {
            "id": f"remed_{uuid.uuid4().hex[:10]}",
            "type": "code",
            "difficulty": difficulty,
            "prompt": prompt,
            "max_score": 5,
            "hints": [],
            "parts": [
                {
                    "key": "solution",
                    "prompt": prompt,
                    "tags": {"primary": "caching"},
                    "max_score": 5,
                    "difficulty": difficulty,
                    "scaffold": "def solution():\n    # TODO\n    pass\n",
                }
            ],
            "generated": True,
            "generated_kind": "challenge",
            "target_text": "",
            "context_notes": "",
            "tags": {"primary": "caching"},
        }


def _session(**kwargs):
    s = Session(candidate=kwargs.pop("candidate", "alice@example.com"), **kwargs)
    return s


def _base_task(difficulty=3):
    return {
        "id": "mi_sys_cache",
        "type": "code",
        "difficulty": difficulty,
        "prompt": "Design a cache.",
        "max_score": 5,
        "tags": {"primary": "caching", "secondary": []},
    }


def _result(score=1, max_score=5):
    return type("R", (), {"score": score, "max_score": max_score})()


def _coach(feedback=""):
    return type("C", (), {"feedback": feedback})()


class TestPickNextTask:
    """Hybrid picker (coach.selection.pick_next_task)."""

    def test_pending_generated_task_surfaces_first(self):
        from coach.selection import pick_next_task

        session = _session(tasks=[_base_task()])
        generated = {
            "id": "remed_pending",
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

    def test_stray_generated_task_is_not_pending(self):
        """A persisted generated task must not shadow the bank in a session."""
        from coach.selection import pick_next_task

        session = _session(tasks=[_base_task()])
        session.tasks.append(
            {
                "id": "remed_stray",
                "type": "code",
                "difficulty": 2,
                "prompt": "Old leftover drill.",
                "max_score": 5,
                "generated": True,
                "target_text": "leftover",
                "tags": {"primary": "ablations", "secondary": []},
            }
        )
        picked = pick_next_task(session.candidate, session)
        assert picked is not None
        assert picked["id"] == "mi_sys_cache"

    def test_challenge_respects_requested_node(self, monkeypatch):
        """When the bank has no task for a node, the minted challenge stays
        inside that node's subtree (it used to ignore the node entirely)."""
        import coach.remediation as remediation
        from coach.selection import pick_next_task
        from coach.taxonomy import area_of

        captured: dict = {}

        def fake_plan_challenge(session, planner=None, prefer_node=""):
            captured["prefer_node"] = prefer_node
            return {
                "id": "remed_challenge",
                "type": "code",
                "difficulty": 2,
                "prompt": "Challenge.",
                "max_score": 5,
                "parts": [
                    {
                        "key": "solution",
                        "prompt": "Challenge.",
                        "tags": {"primary": prefer_node or "tool_use"},
                        "max_score": 5,
                        "difficulty": 2,
                    }
                ],
                "generated": True,
                "generated_kind": "challenge",
                "target_text": "",
                "tags": {"primary": prefer_node or "tool_use", "secondary": []},
            }

        monkeypatch.setattr(remediation, "plan_challenge", fake_plan_challenge)
        session = _session()
        session.tasks = []
        picked = pick_next_task(session.candidate, session, node="agents")
        assert picked is not None
        assert area_of(captured["prefer_node"]) == "agents"

    def test_bank_picker_fallback(self):
        from coach.selection import pick_next_task

        session = _session(tasks=[_base_task()])
        picked = pick_next_task(session.candidate, session)
        assert picked is not None
        assert picked["id"] == "mi_sys_cache"

    def test_bank_exhausted_mints_challenge(self, monkeypatch):
        from coach.selection import pick_next_task

        session = _session(tasks=[_base_task()])
        session.asked_task_ids.add("mi_sys_cache")
        # Hermetic: force challenge generation to fail -> session ends.
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        assert pick_next_task(session.candidate, session) is None

    def test_read_path_never_mints(self, monkeypatch):
        """allow_generation=False must not spend an LLM call or inject a task."""
        import coach.remediation as remediation
        from coach.selection import pick_next_task

        def boom(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("read path minted a task")

        monkeypatch.setattr(remediation, "plan_followup", boom)
        monkeypatch.setattr(remediation, "plan_challenge", boom)
        session = _session(tasks=[_base_task()])
        session.asked_task_ids.add("mi_sys_cache")
        assert pick_next_task(
            session.candidate, session, allow_generation=False
        ) is None

    def test_read_path_still_reuses_pending_generated(self):
        """A task already injected by a prior write still surfaces on read."""
        from coach.selection import pick_next_task

        session = _session(tasks=[_base_task()])
        pending = {
            "id": "remed_pending_read",
            "type": "code",
            "difficulty": 2,
            "prompt": "Warm-up.",
            "max_score": 5,
            "generated": True,
            "target_text": "gap",
        }
        session.add_generated_task(pending)
        picked = pick_next_task(
            session.candidate, session, allow_generation=False
        )
        assert picked is not None
        assert picked["id"] == "remed_pending_read"


class TestTrigger:
    def test_incorrect_answer_triggers(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        gen = planner.decide(_session(), _base_task(), _result(1, 5), _coach("gap"))
        assert gen is not None
        assert gen["generated"] is True
        assert gen["target_text"] == "gap"
        assert gen["difficulty"] <= _base_task()["difficulty"]

    def test_partially_correct_triggers(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        gen = planner.decide(_session(), _base_task(), _result(2, 5), _coach("weak loop"))
        assert gen is not None

    def test_correct_without_gap_does_not_trigger(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        gen = planner.decide(_session(), _base_task(), _result(5, 5), _coach(""))
        assert gen is None

    def test_named_gap_triggers_even_on_correct(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        gen = planner.decide(
            _session(), _base_task(), _result(5, 5),
            _coach("Confused eviction with invalidation"),
        )
        assert gen is not None
        assert gen["target_text"] == "Confused eviction with invalidation"
        # Consolidation repetition never gets harder than the original.
        assert gen["difficulty"] <= _base_task()["difficulty"]

    def test_feedback_gap_triggers(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer)
        gen = planner.decide(_session(), _base_task(), _result(1, 5), _coach("Off-by-one in loop"))
        assert gen is not None
        assert decomposer.calls[-1][0] == "Off-by-one in loop"


class TestBudgetGuards:
    def test_per_session_cap(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer, max_per_session=1)
        session = _session()
        gen = planner.decide(session, _base_task(), _result(1, 5), _coach("gap"))
        assert gen is not None
        assert "skill" not in gen
        session.add_generated_task(gen)
        # Second attempt blocked by session cap.
        assert planner.decide(session, _base_task(), _result(1, 5), _coach("gap")) is None

    def test_followup_is_session_only(self, tmp_path, monkeypatch):
        """Generated drills live in the session, never in the task bank."""
        import coach.db as db

        monkeypatch.setattr(db, "DB_PATH", tmp_path / "remed.db")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        from coach.remediation import RemediationPlanner, plan_followup

        planner = RemediationPlanner(decomposer=FakeDecomposer())
        session = _session()
        session.tasks = [_base_task()]
        gen = plan_followup(session, _base_task(), _result(1, 5), _coach("eviction gap"), planner=planner)
        assert gen is not None
        assert gen in session.tasks
        assert gen["id"] in session.generated_task_ids
        # Not persisted: a session artifact must not add a bank row (that is
        # what orphaned generated tasks when the owning session went away).
        from coach.tasks import get_task

        assert get_task(gen["id"]) is None


class TestAdaptiveChain:
    """Solved drill -> harder escalation -> sibling-prerequisite pivot."""

    def _solved(self):
        return _result(5, 5)

    def test_solved_drill_escalates_harder(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer)
        session = _session(tasks=[_base_task(difficulty=3)])
        drill = planner.decide(session, _base_task(difficulty=3), _result(1, 5), _coach("eviction gap"))
        assert drill is not None
        assert decomposer.calls[-1][3] == "remediate"
        session.add_generated_task(drill)
        # Solve the drill cleanly -> escalation at same-or-harder difficulty.
        esc = planner.decide(session, drill, self._solved(), _coach(""))
        assert esc is not None
        assert decomposer.calls[-1][3] == "escalate"
        assert esc["difficulty"] >= drill["difficulty"]
        assert esc["root_task_id"] == "mi_sys_cache"

    def test_solved_escalation_pivots(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer)
        session = _session(tasks=[_base_task(difficulty=3)])
        drill = planner.decide(session, _base_task(difficulty=3), _result(1, 5), _coach("eviction gap"))
        session.add_generated_task(drill)
        esc = planner.decide(session, drill, self._solved(), _coach(""))
        session.add_generated_task(esc)
        pivot = planner.decide(session, esc, self._solved(), _coach(""))
        assert pivot is not None
        assert decomposer.calls[-1][3] == "pivot"

    def test_failed_drill_drills_simpler_again(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer)
        session = _session(tasks=[_base_task(difficulty=3)])
        drill = planner.decide(session, _base_task(difficulty=3), _result(1, 5), _coach("eviction gap"))
        session.add_generated_task(drill)
        again = planner.decide(session, drill, _result(1, 5), _coach("still confused"))
        assert again is not None
        assert decomposer.calls[-1][3] == "remediate"
        assert again["difficulty"] <= drill["difficulty"]

    def test_chain_cap_per_root(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer, max_chain_per_root=1)
        session = _session(tasks=[_base_task(difficulty=3)])
        drill = planner.decide(session, _base_task(difficulty=3), _result(1, 5), _coach("gap"))
        assert drill is not None
        session.add_generated_task(drill)
        assert planner.decide(session, drill, self._solved(), _coach("")) is None

    def test_challenge_keeps_session_going(self):
        from coach.remediation import plan_challenge

        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer)
        session = _session(tasks=[_base_task()])
        session.asked_task_ids.add("mi_sys_cache")
        gen = plan_challenge(session, planner=planner)
        assert gen is not None
        assert gen["generated_kind"] == "challenge"
        assert gen in session.tasks
