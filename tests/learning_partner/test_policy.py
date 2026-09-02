"""Stage 8 tests: adaptive next-action selection."""

from __future__ import annotations

import pytest

from core.learning_partner.domain.action import ActionType
from core.learning_partner.domain.learner import LearnerKnowledgeState, StateStatus
from core.learning_partner.seed import seed_weighted_sampling, seed_weighted_sampling_task


@pytest.fixture()
def ctx(seeded_repository, learner_service, policy_engine, task_repository, target_repository):
    seed_weighted_sampling_task(task_repository, target_repository, seeded_repository)
    learner = learner_service.create_learner()
    return {
        "repo": seeded_repository,
        "learner_service": learner_service,
        "policy": policy_engine,
        "learner": learner,
    }


def _set_state(ctx, slug, mastery, uncertainty, evidence_count, status):
    node = ctx["repo"].get_node_by_slug(slug)
    state = LearnerKnowledgeState(
        learner_id=ctx["learner"].id,
        node_id=node.id,
        mastery=mastery,
        uncertainty=uncertainty,
        evidence_count=evidence_count,
        status=status,
    )
    ctx["learner_service"].upsert_state(state)
    return node


class TestActionSelection:
    def test_engine_targets_weak_area_not_strong(self, ctx):
        """Strong normalize/construct; weak binary/complexity/boundary.

        The engine must pick an action targeting one of the weak areas, not
        reteach normalization.
        """
        strong = [
            _set_state(ctx, "normalize_weights", 0.9, 0.05, 8, StateStatus.MASTERED),
            _set_state(ctx, "construct_cdf", 0.9, 0.05, 8, StateStatus.MASTERED),
        ]
        weak = [
            _set_state(ctx, "binary_search_cdf", 0.5, 1.0, 0, StateStatus.UNKNOWN),
            _set_state(ctx, "analyze_sampling_complexity", 0.5, 0.6, 1, StateStatus.UNCERTAIN),
            _set_state(ctx, "handle_boundaries", 0.3, 0.5, 2, StateStatus.DEVELOPING),
        ]
        weak_ids = {n.id for n in weak}
        strong_ids = {n.id for n in strong}

        problem = ctx["repo"].get_node_by_slug("weighted_sampling_from_scratch")
        from core.learning_partner.services.frontier import FrontierService

        # Build frontier through the policy's own inputs by calling generate directly.
        # Use frontier_service from container-like wiring (policy reads states directly).
        actions = ctx["policy"].generate(ctx["learner"].id, self._frontier(ctx))
        assert actions, "expected at least one candidate action"
        top = actions[0]
        assert top.target_node_id in weak_ids
        assert top.target_node_id not in strong_ids

    @staticmethod
    def _frontier(ctx):
        from core.learning_partner.domain.frontier import FrontierStatus

        states = ctx["learner_service"].list_learner_states(ctx["learner"].id)
        problem = ctx["repo"].get_node_by_slug("weighted_sampling_from_scratch")
        # Reuse the frontier service through a manual pass: simulate frontier entries.
        from core.learning_partner.domain.frontier import LearnerFrontier
        from core.learning_partner.domain.knowledge import utcnow

        entries = []
        for s in states:
            if s.status in (StateStatus.UNKNOWN, StateStatus.UNCERTAIN, StateStatus.DEVELOPING):
                entries.append(LearnerFrontier(
                    learner_id=ctx["learner"].id,
                    node_id=s.node_id,
                    priority=s.uncertainty,
                    reason="uncertain",
                    status=FrontierStatus.CANDIDATE,
                    created_at=utcnow(), updated_at=utcnow(),
                ))
        return entries


class TestActionTypes:
    def test_mastered_low_uncertainty_gets_recap_or_low_priority(self, ctx):
        node = _set_state(ctx, "normalize_weights", 0.95, 0.05, 8, StateStatus.MASTERED)
        actions = ctx["policy"].generate(ctx["learner"].id, self._make_frontier(ctx, node))
        assert actions
        assert actions[0].action_type in (ActionType.RECAP, ActionType.CHALLENGE)

    def test_high_mastery_high_uncertainty_probes(self, ctx):
        node = _set_state(ctx, "construct_cdf", 0.8, 0.8, 4, StateStatus.UNCERTAIN)
        actions = ctx["policy"].generate(ctx["learner"].id, self._make_frontier(ctx, node))
        assert actions[0].action_type == ActionType.PROBE

    def test_low_mastery_low_uncertainty_teaches(self, ctx):
        node = _set_state(ctx, "handle_boundaries", 0.3, 0.1, 3, StateStatus.DEVELOPING)
        actions = ctx["policy"].generate(ctx["learner"].id, self._make_frontier(ctx, node))
        assert actions[0].action_type == ActionType.EXPLAIN

    def test_low_mastery_high_uncertainty_diagnoses(self, ctx):
        node = _set_state(ctx, "binary_search_cdf", 0.3, 0.9, 1, StateStatus.UNCERTAIN)
        actions = ctx["policy"].generate(ctx["learner"].id, self._make_frontier(ctx, node))
        assert actions[0].action_type == ActionType.PROBE

    @staticmethod
    def _make_frontier(ctx, node):
        from core.learning_partner.domain.frontier import FrontierStatus, LearnerFrontier
        from core.learning_partner.domain.knowledge import utcnow

        return [LearnerFrontier(
            learner_id=ctx["learner"].id,
            node_id=node.id,
            priority=0.9,
            reason="test",
            status=FrontierStatus.CANDIDATE,
            created_at=utcnow(), updated_at=utcnow(),
        )]


class TestMisconceptionBoost:
    def test_misconception_probe_is_strong_candidate(self, ctx, misconception_service, repository):
        from core.learning_partner.seed import seed_misconceptions

        seed_misconceptions(repository)
        mc_node = repository.get_node_by_slug("cdf_is_normalized_weights")
        mc = misconception_service.suspect_misconception(ctx["learner"].id, mc_node.id)
        actions = ctx["policy"].generate(ctx["learner"].id, [])
        mc_actions = [a for a in actions if a.action_type == ActionType.MISCONCEPTION_PROBE]
        assert mc_actions, "misconception probe should be generated"
        assert any(a.target_node_id == mc_node.id for a in mc_actions)