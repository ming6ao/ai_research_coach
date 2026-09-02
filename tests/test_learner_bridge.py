"""Integration tests for the learning-partner bridge.

Uses a fake decomposer + fake judge so no LLM call is made. The MVP DB is a
fresh temp file per test (via LEARNING_PARTNER_DB_URL).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

# Point the MVP at a per-test DB before importing the bridge (module reads env at init).
from evaluators.base import CoachContent, EvaluationResult
from core.task_decomposer import DecomposedEdge, DecomposedNode, TaskKnowledge
from core.learning_partner.domain.types import EdgeType, NodeType


class FakeDecomposer:
    """Deterministic decomposition used by tests (no LLM)."""

    def decompose(self, task: dict) -> TaskKnowledge:
        skill = task.get("skill", "general")
        skill_slug = skill.lower().replace("_", "-")
        return TaskKnowledge(
            task_id=task["id"],
            skill=skill,
            primary_node_slug=skill_slug,
            nodes=[
                DecomposedNode(type=NodeType.SKILL, slug=skill_slug, name=skill.title(), importance=0.9),
                DecomposedNode(type=NodeType.CONCEPT, slug=f"{skill_slug}-basics", name=f"{skill} basics", importance=0.6),
            ],
            edges=[
                DecomposedEdge(skill_slug, f"{skill_slug}-basics", EdgeType.REQUIRES),
            ],
        )


@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    # Isolate both the MVP DB and the parent's coach.db per test.
    from core import storage

    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "coach.db")
    monkeypatch.setenv("LEARNING_PARTNER_DB_URL", f"sqlite:///{tmp_path}/learner.db")
    from core.learner_bridge import LearnerBridge

    b = LearnerBridge(db_url=f"sqlite:///{tmp_path}/learner.db", decomposer=FakeDecomposer())
    return b


def _task(task_id="mi_sys_cache", skill="ml_systems", score=5):
    return {
        "id": task_id,
        "skill": skill,
        "type": "code",
        "difficulty": 3,
        "prompt": f"Implement {task_id}.",
        "max_score": 5,
    }


def _result(task, score):
    coach = CoachContent(feedback="ok", misconception="", steps=[])
    return EvaluationResult(task["id"], task["skill"], score, task["max_score"], "rationale", coach.to_dict()), coach


class TestLearnerIdentity:
    def test_ensure_learner_is_idempotent(self, bridge):
        lid1 = bridge.ensure_learner("alice@example.com")
        lid2 = bridge.ensure_learner("alice@example.com")
        assert lid1 == lid2

    def test_learners_are_distinct_per_candidate(self, bridge):
        a = bridge.ensure_learner("alice@example.com")
        b = bridge.ensure_learner("bob@example.com")
        assert a != b

    def test_guest_candidate_gets_a_learner(self, bridge):
        lid = bridge.ensure_learner("guest-abc123")
        assert lid is not None


class TestBootstrap:
    def test_bootstrap_creates_nodes_and_task(self, bridge):
        boot = bridge.bootstrap_task(_task())
        assert boot["mvp_task_id"]
        assert boot["primary_node_slug"] == "ml-systems"

        session = bridge._session()
        try:
            c = bridge._container(session)
            assert c.knowledge_repository.get_node_by_slug("ml-systems") is not None
            assert c.knowledge_repository.get_node_by_slug("ml-systems-basics") is not None
            tasks = [t for t in c.task_repository.list_tasks() if t.metadata.get("coach_task_id") == "mi_sys_cache"]
            assert len(tasks) == 1
        finally:
            session.close()

    def test_bootstrap_is_idempotent(self, bridge):
        b1 = bridge.bootstrap_task(_task())
        b2 = bridge.bootstrap_task(_task())
        assert b1["mvp_task_id"] == b2["mvp_task_id"]
        session = bridge._session()
        try:
            c = bridge._container(session)
            assert len([t for t in c.task_repository.list_tasks() if t.metadata.get("coach_task_id") == "mi_sys_cache"]) == 1
        finally:
            session.close()

    def test_custom_question_bootstraps_via_general(self, bridge):
        task = _task(task_id="custom_abc", skill="general", score=5)
        boot = bridge.bootstrap_task(task)
        assert boot["primary_node_slug"] == "general"


class TestSubmission:
    def test_correct_submission_raises_mastery(self, bridge):
        task = _task(score=5)
        bridge.bootstrap_task(task)
        bridge.ensure_learner("carol@example.com")
        result, coach = _result(task, 5)

        bridge.record_submission("carol@example.com", task, result, coach)
        snap = bridge.learner_snapshot("carol@example.com")
        state = snap["states"]["ml-systems"]
        assert state["mastery"] > 0.5
        assert state["status"] in ("uncertain", "developing", "proficient")

    def test_incorrect_submission_lowers_mastery(self, bridge):
        task = _task(score=5)
        bridge.bootstrap_task(task)
        bridge.ensure_learner("dave@example.com")
        result, coach = _result(task, 1)

        bridge.record_submission("dave@example.com", task, result, coach)
        snap = bridge.learner_snapshot("dave@example.com")
        assert snap["states"]["ml-systems"]["mastery"] < 0.5

    def test_evidence_is_append_only(self, bridge):
        task = _task(score=5)
        bridge.bootstrap_task(task)
        bridge.ensure_learner("erin@example.com")
        result, coach = _result(task, 5)
        out = bridge.record_submission("erin@example.com", task, result, coach)
        assert len(out["evidence_ids"]) >= 1

        # No update/delete path exists on the MVP evidence repository.
        session = bridge._session()
        try:
            c = bridge._container(session)
            assert not hasattr(c.evidence_repository, "update_evidence")
            assert not hasattr(c.evidence_repository, "delete_evidence")
        finally:
            session.close()

    def test_frontier_updates_after_submission(self, bridge):
        task = _task(score=5)
        bridge.bootstrap_task(task)
        bridge.ensure_learner("frank@example.com")
        result, coach = _result(task, 3)

        out = bridge.record_submission("frank@example.com", task, result, coach)
        assert len(out["frontier"]) >= 1
        snap = bridge.learner_snapshot("frank@example.com")
        assert len(snap["frontier_top"]) >= 1

    def test_misconception_created_from_low_score_and_coach(self, bridge):
        task = _task(score=5)
        bridge.bootstrap_task(task)
        bridge.ensure_learner("grace@example.com")
        coach = CoachContent(feedback="no", misconception="Confused caching with eviction.", steps=[])
        result = EvaluationResult(task["id"], task["skill"], 1, task["max_score"], "x", coach.to_dict())

        out = bridge.record_submission("grace@example.com", task, result, coach)
        assert out["misconception"] is not None
        assert out["misconception"]["slug"] == "confused-caching-with-eviction"
        snap = bridge.learner_snapshot("grace@example.com")
        assert any(m["status"] == "suspected" for m in snap["misconceptions"])

    def test_no_misconception_on_high_score(self, bridge):
        task = _task(score=5)
        bridge.bootstrap_task(task)
        bridge.ensure_learner("hank@example.com")
        result, coach = _result(task, 5)
        out = bridge.record_submission("hank@example.com", task, result, coach)
        assert out["misconception"] is None

    def test_next_action_points_to_gap(self, bridge):
        task = _task(score=5)
        bridge.bootstrap_task(task)
        bridge.ensure_learner("ivy@example.com")
        result, coach = _result(task, 1)
        out = bridge.record_submission("ivy@example.com", task, result, coach)
        # After a failing submission, the learner should be probed/taught, not moved on.
        assert out["next_action"] is not None
        assert out["next_action"]["action_type"] in ("probe", "explain", "misconception_probe", "code")


class TestNotObserved:
    def test_not_observed_evidence_not_incorrect(self, bridge):
        """The bridge never creates not_observed evidence; but the MVP rule holds."""
        task = _task(score=5)
        bridge.bootstrap_task(task)
        bridge.ensure_learner("joe@example.com")

        session = bridge._session()
        try:
            c = bridge._container(session)
            from core.learning_partner.domain.evidence import Evidence, EvidenceType, ObservationStatus

            node = c.knowledge_repository.get_node_by_slug("ml-systems")
            c.evidence_service.add_evidence(
                Evidence(
                    learner_id=bridge.ensure_learner("joe@example.com"),
                    node_id=node.id,
                    evidence_type=EvidenceType.ANSWER,
                    observation_status=ObservationStatus.NOT_OBSERVED,
                )
            )
            summary = c.evidence_service.summarize(bridge.ensure_learner("joe@example.com"), node.id)
            assert summary.incorrect_count == 0
        finally:
            session.close()


class TestSnapshot:
    def test_snapshot_empty_for_unknown_candidate(self, bridge):
        snap = bridge.learner_snapshot("nobody@example.com")
        assert snap["learner_id"] is None
        assert snap["states"] == {}

    def test_snapshot_contains_states_frontier_misconceptions(self, bridge):
        task = _task(score=5)
        bridge.bootstrap_task(task)
        bridge.ensure_learner("kim@example.com")
        result, coach = _result(task, 1)
        bridge.record_submission("kim@example.com", task, result, coach)
        snap = bridge.learner_snapshot("kim@example.com")
        assert "ml-systems" in snap["states"]
        assert isinstance(snap["frontier_top"], list)
        assert isinstance(snap["misconceptions"], list)


class TestCli:
    def test_demo_prints_snapshot(self, tmp_path, monkeypatch, capsys):
        from core import storage
        from core.learner_bridge import main

        monkeypatch.setattr(storage, "DB_PATH", tmp_path / "coach.db")
        url = f"sqlite:///{tmp_path}/learner.db"
        exit_code = main(["--demo", "--db", url])
        out = capsys.readouterr().out

        assert exit_code == 0
        assert "Learner snapshot for demo@example.com" in out
        assert "mastery=" in out
        assert "next_action:" in out

    def test_inspect_existing_candidate(self, bridge, tmp_path, monkeypatch, capsys):
        from core import storage
        from core.learner_bridge import main

        monkeypatch.setattr(storage, "DB_PATH", tmp_path / "coach.db")
        bridge.ensure_learner("cli@example.com")
        # Reuse the same bridge DB for the CLI lookup.
        url = bridge._db_url
        exit_code = main(["cli@example.com", "--db", url])
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "Learner snapshot for cli@example.com" in out

    def test_missing_candidate_prints_help(self, tmp_path, monkeypatch, capsys):
        from core import storage
        from core.learner_bridge import main

        monkeypatch.setattr(storage, "DB_PATH", tmp_path / "coach.db")
        exit_code = main([], )
        out = capsys.readouterr().out
        assert exit_code == 2
        assert "usage" in out.lower() or "inspect" in out.lower()