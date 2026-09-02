"""Tests for the iterative remediation planner.

Uses a fake decomposer (no LLM) so the deterministic path is exercised, plus
direct checks of the budget guards, trigger logic, and target selection.
"""

from __future__ import annotations

import uuid

from core.remediation import (
    RemediationPlanner,
    MAX_PER_SKILL,
    MAX_PER_SESSION,
    UNCERTAINTY_REMEDIATE_AT,
    UNCERTAINTY_STOP_AT,
)
from core.session import Session


class FakeDecomposer:
    """Records calls; returns a deterministic generated task (fallback-style)."""

    def __init__(self):
        self.calls = []

    def generate_remediation_task(self, node, original_task, original_fraction):
        self.calls.append((node, original_task, original_fraction))
        return {
            "id": f"remed_{uuid.uuid4().hex[:10]}",
            "skill": original_task.get("skill", "general"),
            "type": "code",
            "difficulty": max(1, int(original_task.get("difficulty", 2)) - 1),
            "prompt": f"Simpler task for {node.get('slug')}.",
            "max_score": 5,
            "hints": [],
            "generated": True,
            "mvp_target_slug": node.get("slug"),
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


def _learner_update(status="incorrect", fraction=0.2, frontier=None, next_action=None, misconceptions=False):
    frontier = frontier or [
        {"node_id": str(uuid.uuid4()), "slug": "cache-eviction", "name": "Cache Eviction", "description": "Choosing what to drop.", "priority": 0.9, "reason": "uncertain"},
        {"node_id": str(uuid.uuid4()), "slug": "cache-invalidation", "name": "Cache Invalidation", "description": "Keeping stale data out.", "priority": 0.8, "reason": "uncertain"},
    ]
    next_action = next_action or {"action_type": "code", "target_node_id": frontier[0]["node_id"], "slug": frontier[0]["slug"], "name": frontier[0]["name"], "description": frontier[0]["description"]}
    return {
        "observation_status": status,
        "fraction": fraction,
        "frontier": frontier,
        "next_action": next_action,
        "misconception": None,
    }


def _snapshot(uncertainties=None, misconceptions=None):
    uncertainties = uncertainties or {"cache-eviction": 0.8, "cache-invalidation": 0.7}
    return {
        "states": {
            slug: {"mastery": 0.4, "uncertainty": u, "status": "uncertain", "evidence_count": 1}
            for slug, u in uncertainties.items()
        },
        "misconceptions": misconceptions or [],
    }


class TestTrigger:
    def test_incorrect_answer_triggers(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        gen = planner.decide(
            _session(), _base_task(), None,
            _learner_update(status="incorrect", fraction=0.2), _snapshot(),
        )
        assert gen is not None
        assert gen["generated"] is True
        assert gen["mvp_target_slug"] == "cache-eviction"

    def test_partially_correct_triggers(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        gen = planner.decide(
            _session(), _base_task(), None,
            _learner_update(status="partially_correct", fraction=0.5), _snapshot(),
        )
        assert gen is not None

    def test_correct_but_high_uncertainty_triggers(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        gen = planner.decide(
            _session(), _base_task(), None,
            _learner_update(status="correct", fraction=0.9), _snapshot(),
        )
        assert gen is not None

    def test_correct_and_confident_does_not_trigger(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        snap = _snapshot(uncertainties={"cache-eviction": 0.05, "cache-invalidation": 0.05})
        gen = planner.decide(
            _session(), _base_task(), None,
            _learner_update(status="correct", fraction=0.95), snap,
        )
        assert gen is None

    def test_active_misconception_triggers_even_on_correct(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        snap = _snapshot(misconceptions=[{"slug": "confused-eviction", "status": "suspected"}])
        gen = planner.decide(
            _session(), _base_task(), None,
            _learner_update(status="correct", fraction=0.9), snap,
        )
        assert gen is not None


class TestTargetSelection:
    def test_uses_next_action_target(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        action = {"action_type": "code", "target_node_id": "n1", "slug": "cache-invalidation", "name": "Cache Invalidation", "description": "Keeping stale data out."}
        gen = planner.decide(
            _session(), _base_task(), None,
            _learner_update(status="incorrect", next_action=action), _snapshot(),
        )
        assert gen["mvp_target_slug"] == "cache-invalidation"

    def test_generated_task_uses_real_node_name_and_description(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer)
        action = {"action_type": "code", "target_node_id": "n1", "slug": "cache-invalidation", "name": "Cache Invalidation", "description": "Keeping stale data out."}
        gen = planner.decide(
            _session(), _base_task(), None,
            _learner_update(status="incorrect", next_action=action), _snapshot(),
        )
        assert gen is not None
        assert gen["mvp_target_slug"] == "cache-invalidation"
        node = decomposer.calls[-1][0]
        assert node["name"] == "Cache Invalidation"
        assert node["description"] == "Keeping stale data out."

    def test_node_dict_falls_back_to_slug_when_name_absent(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer)
        action = {"action_type": "code", "target_node_id": "n1", "slug": "cache-invalidation"}
        gen = planner.decide(
            _session(), _base_task(), None,
            _learner_update(status="incorrect", next_action=action), _snapshot(),
        )
        assert gen is not None
        node = decomposer.calls[-1][0]
        assert node["name"] == "Cache Invalidation"  # slug-derived fallback
        assert node["description"] == "uncertain"  # falls back to node status

    def test_falls_back_to_highest_uncertainty_when_no_action(self):
        planner = RemediationPlanner(decomposer=FakeDecomposer())
        upd = _learner_update(status="incorrect")
        upd["next_action"] = None
        gen = planner.decide(_session(), _base_task(), None, upd, _snapshot())
        assert gen is not None


class TestBudgetGuards:
    def test_per_skill_cap(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer, max_per_skill=1, max_per_session=10)
        session = _session()
        for _ in range(2):
            gen = planner.decide(session, _base_task(), None, _learner_update(), _snapshot())
            if gen is not None:
                session.add_generated_task(gen)
        # Only one generated task for this skill despite two opportunities.
        assert sum(1 for t in session.tasks if t.get("generated")) == 1
        assert len(decomposer.calls) == 1  # second call was refused before generating

    def test_per_session_cap(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer, max_per_skill=10, max_per_session=1)
        session = _session()
        gen = planner.decide(session, _base_task(), None, _learner_update(), _snapshot())
        assert gen is not None
        session.add_generated_task(gen)
        # Second attempt blocked by session cap.
        assert planner.decide(session, _base_task(), None, _learner_update(), _snapshot()) is None

    def test_confident_target_not_actionable(self):
        decomposer = FakeDecomposer()
        planner = RemediationPlanner(decomposer=decomposer)
        snap = _snapshot(uncertainties={"cache-eviction": 0.05})
        gen = planner.decide(_session(), _base_task(), None, _learner_update(), snap)
        assert gen is None
        assert decomposer.calls == []
