"""Stage 7 tests: learner-specific Learning Frontier."""

from __future__ import annotations

import pytest

from learning_partner.domain.frontier import FrontierStatus
from learning_partner.domain.learner import LearnerKnowledgeState, StateStatus
from learning_partner.seed import seed_weighted_sampling, seed_weighted_sampling_task
from learning_partner.services.frontier import FrontierService


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
    return ctx["learner_service"].upsert_state(state), node


@pytest.fixture()
def ctx(seeded_repository, learner_service, frontier_repo, repository):
    """No assessment tasks seeded, so task targets do not leak into generation."""
    learner = learner_service.create_learner()
    frontier_service = FrontierService(
        frontier_repo, learner_service._learners, repository
    )
    return {
        "repo": seeded_repository,
        "learner_service": learner_service,
        "frontier_service": frontier_service,
        "learner": learner,
    }


@pytest.fixture()
def task_ctx(
    seeded_repository,
    learner_service,
    frontier_service,
    task_repository,
    target_repository,
):
    seed_weighted_sampling_task(task_repository, target_repository, seeded_repository)
    learner = learner_service.create_learner()
    return {
        "repo": seeded_repository,
        "learner_service": learner_service,
        "frontier_service": frontier_service,
        "learner": learner,
    }


class TestGeneration:
    def test_given_scenario_prioritizes_gaps(self, ctx):
        """normalize/construct mastered; binary unknown; complexity uncertain; boundary low."""
        _, normalize = _set_state(ctx, "normalize_weights", 0.9, 0.05, 8, StateStatus.MASTERED)
        _, cdf = _set_state(ctx, "construct_cdf", 0.9, 0.05, 8, StateStatus.MASTERED)
        _, binary = _set_state(ctx, "binary_search_cdf", 0.5, 1.0, 0, StateStatus.UNKNOWN)
        _, complexity = _set_state(ctx, "analyze_sampling_complexity", 0.5, 0.6, 1, StateStatus.UNCERTAIN)
        _, boundary = _set_state(ctx, "handle_boundaries", 0.3, 0.5, 2, StateStatus.DEVELOPING)

        problem = ctx["repo"].get_node_by_slug("weighted_sampling_from_scratch")
        frontier = ctx["frontier_service"].generate(ctx["learner"].id, problem.id)

        by_id = {f.node_id: f for f in frontier}
        # The three gaps are on the frontier.
        for node in (binary, complexity, boundary):
            assert node.id in by_id, f"{node.slug} should be on frontier"
        # Mastered skills are not prioritized.
        assert normalize.id not in by_id
        assert cdf.id not in by_id

    def test_task_required_pulls_mastered_node_in(self, task_ctx):
        """A mastered node required by the seeded task appears (filter exemption)."""
        _, cdf = _set_state(task_ctx, "construct_cdf", 0.9, 0.05, 8, StateStatus.MASTERED)
        problem = task_ctx["repo"].get_node_by_slug("weighted_sampling_from_scratch")
        frontier = task_ctx["frontier_service"].generate(task_ctx["learner"].id, problem.id)
        entry = next((f for f in frontier if f.node_id == cdf.id), None)
        assert entry is not None
        assert entry.reason == "task_required"

    def test_reasons_are_recorded(self, ctx):
        _, binary = _set_state(ctx, "binary_search_cdf", 0.5, 1.0, 0, StateStatus.UNKNOWN)
        problem = ctx["repo"].get_node_by_slug("weighted_sampling_from_scratch")
        frontier = ctx["frontier_service"].generate(ctx["learner"].id, problem.id)
        entry = next(f for f in frontier if f.node_id == binary.id)
        assert entry.reason == "uncertain"

    def test_empty_learner_has_frontier_from_related(self, ctx):
        problem = ctx["repo"].get_node_by_slug("weighted_sampling_from_scratch")
        frontier = ctx["frontier_service"].generate(ctx["learner"].id, problem.id)
        assert len(frontier) >= 1


class TestStatus:
    def test_set_status(self, ctx):
        _, binary = _set_state(ctx, "binary_search_cdf", 0.5, 1.0, 0, StateStatus.UNKNOWN)
        problem = ctx["repo"].get_node_by_slug("weighted_sampling_from_scratch")
        ctx["frontier_service"].generate(ctx["learner"].id, problem.id)
        ctx["frontier_service"].set_status(ctx["learner"].id, binary.id, FrontierStatus.ACTIVE)
        entries = ctx["frontier_service"].list_frontier(ctx["learner"].id)
        entry = next(f for f in entries if f.node_id == binary.id)
        assert entry.status == FrontierStatus.ACTIVE

    def test_list_frontier_sorted_by_priority(self, ctx):
        _, binary = _set_state(ctx, "binary_search_cdf", 0.5, 1.0, 0, StateStatus.UNKNOWN)
        _, complexity = _set_state(ctx, "analyze_sampling_complexity", 0.5, 0.6, 1, StateStatus.UNCERTAIN)
        problem = ctx["repo"].get_node_by_slug("weighted_sampling_from_scratch")
        ctx["frontier_service"].generate(ctx["learner"].id, problem.id)
        entries = ctx["frontier_service"].list_frontier(ctx["learner"].id)
        priorities = [f.priority for f in entries]
        assert priorities == sorted(priorities, reverse=True)