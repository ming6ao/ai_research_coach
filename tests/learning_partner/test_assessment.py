"""Assessment tasks & targets tests.

Uses the Weighted Sampling From Scratch seed graph so targets reference real
nodes.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from core.learning_partner.domain.assessment import (
    AssessmentTask,
    AssessmentTarget,
    TargetRole,
    TaskType,
)
from core.learning_partner.domain.errors import DuplicateTargetError, TaskNotFoundError
from core.learning_partner.seed import seed_weighted_sampling, seed_weighted_sampling_task
from core.learning_partner.seed.assessment_tasks import TASK_SPEC, TARGET_SPECS


@pytest.fixture()
def nodes(assessment_service, repository):
    """Seed the graph and return a {slug: node_id} map."""
    seed_weighted_sampling(repository)
    return {
        "normalize_weights": repository.get_node_by_slug("normalize_weights").id,
        "construct_cdf": repository.get_node_by_slug("construct_cdf").id,
        "binary_search_cdf": repository.get_node_by_slug("binary_search_cdf").id,
        "handle_boundaries": repository.get_node_by_slug("handle_boundaries").id,
    }


def make_task(**overrides) -> AssessmentTask:
    defaults = dict(
        task_type=TaskType.CODING,
        title="Implement weighted sampling",
        prompt="Normalize weights, build CDF, sample.",
        difficulty=0.65,
    )
    defaults.update(overrides)
    return AssessmentTask(**defaults)


class TestTaskCRUD:
    def test_create_task(self, task_repository):
        task = task_repository.create_task(make_task())
        assert task.id is not None
        assert task.task_type == TaskType.CODING
        assert task.difficulty == 0.65

    def test_get_task(self, task_repository):
        task = task_repository.create_task(make_task())
        fetched = task_repository.get_task(task.id)
        assert fetched == task
        assert fetched.title == "Implement weighted sampling"

    def test_get_missing_task_returns_none(self, task_repository):
        assert task_repository.get_task(uuid.uuid4()) is None

    def test_update_task(self, task_repository):
        task = task_repository.create_task(make_task())
        updated = task_repository.update_task(task.id, title="New title", difficulty=0.4)
        assert updated.title == "New title"
        assert updated.difficulty == 0.4
        assert updated.updated_at >= task.updated_at

    def test_update_missing_task_raises(self, task_repository):
        with pytest.raises(TaskNotFoundError):
            task_repository.update_task(uuid.uuid4(), title="x")

    def test_list_tasks(self, task_repository):
        task_repository.create_task(make_task(task_type=TaskType.CODING))
        task_repository.create_task(
            make_task(task_type=TaskType.EXPLANATION, title="Explain CDF")
        )
        all_tasks = task_repository.list_tasks()
        assert len(all_tasks) == 2
        coding = task_repository.list_tasks(task_type=TaskType.CODING)
        assert len(coding) == 1
        assert coding[0].task_type == TaskType.CODING

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            AssessmentTask(task_type=TaskType.CODING, title="t", prompt="p", bogus=1)

    def test_difficulty_bounds(self):
        with pytest.raises(ValidationError):
            make_task(difficulty=1.5)
        with pytest.raises(ValidationError):
            make_task(difficulty=-0.1)


class TestTargetCRUD:
    def test_add_and_list_targets(self, assessment_service, nodes):
        task = assessment_service.create_task(make_task())
        assessment_service.add_target(
            task.id, nodes["normalize_weights"], TargetRole.PRIMARY, 1.0
        )
        targets = assessment_service.list_targets_for_task(task.id)
        assert len(targets) == 1
        t = targets[0]
        assert t.node_id == nodes["normalize_weights"]
        assert t.target_role == TargetRole.PRIMARY
        assert t.expected_signal_strength == 1.0

    def test_multiple_targets_per_task(self, assessment_service, nodes):
        task = assessment_service.create_task(make_task())
        for slug, role, strength in [
            ("normalize_weights", TargetRole.PRIMARY, 1.0),
            ("construct_cdf", TargetRole.PRIMARY, 1.0),
            ("handle_boundaries", TargetRole.DIAGNOSTIC, 0.7),
            ("binary_search_cdf", TargetRole.SECONDARY, 0.6),
        ]:
            assessment_service.add_target(task.id, nodes[slug], role, strength)
        targets = assessment_service.list_targets_for_task(task.id)
        assert len(targets) == 4
        assert {t.node_id for t in targets} == {nodes[s] for s in nodes}

    def test_duplicate_target_rejected(self, assessment_service, nodes):
        task = assessment_service.create_task(make_task())
        assessment_service.add_target(task.id, nodes["construct_cdf"], TargetRole.PRIMARY, 1.0)
        with pytest.raises(DuplicateTargetError):
            assessment_service.add_target(task.id, nodes["construct_cdf"], TargetRole.PRIMARY, 1.0)
        with pytest.raises(DuplicateTargetError):
            assessment_service.add_target(task.id, nodes["construct_cdf"], TargetRole.SECONDARY, 0.5)

    def test_add_target_requires_existing_task(self, assessment_service, nodes):
        with pytest.raises(TaskNotFoundError):
            assessment_service.add_target(uuid.uuid4(), nodes["construct_cdf"], TargetRole.PRIMARY)

    def test_add_target_requires_existing_node(self, assessment_service):
        task = assessment_service.create_task(make_task())
        with pytest.raises(Exception):
            assessment_service.add_target(task.id, uuid.uuid4(), TargetRole.PRIMARY)

    def test_remove_target(self, assessment_service, nodes):
        task = assessment_service.create_task(make_task())
        assessment_service.add_target(task.id, nodes["construct_cdf"], TargetRole.PRIMARY, 1.0)
        assert assessment_service.remove_target(task.id, nodes["construct_cdf"]) is True
        assert assessment_service.remove_target(task.id, nodes["construct_cdf"]) is False
        assert assessment_service.list_targets_for_task(task.id) == []

    def test_target_role_filter(self, assessment_service, nodes):
        task = assessment_service.create_task(make_task())
        assessment_service.add_target(task.id, nodes["normalize_weights"], TargetRole.PRIMARY, 1.0)
        assessment_service.add_target(task.id, nodes["handle_boundaries"], TargetRole.DIAGNOSTIC, 0.7)
        assessment_service.add_target(task.id, nodes["binary_search_cdf"], TargetRole.SECONDARY, 0.6)

        primary = assessment_service.list_targets_for_task(task.id, role=TargetRole.PRIMARY)
        assert [t.node_id for t in primary] == [nodes["normalize_weights"]]
        assert len(assessment_service.list_targets_for_task(task.id, role=TargetRole.DIAGNOSTIC)) == 1


class TestCrossTask:
    def test_multiple_tasks_targeting_same_node(self, assessment_service, nodes):
        t1 = assessment_service.create_task(make_task(title="Task A"))
        t2 = assessment_service.create_task(make_task(title="Task B", task_type=TaskType.TRACE))
        for task in (t1, t2):
            assessment_service.add_target(task.id, nodes["construct_cdf"], TargetRole.PRIMARY, 1.0)

        tasks = assessment_service.find_tasks_for_node(nodes["construct_cdf"])
        assert {t.id for t in tasks} == {t1.id, t2.id}

        targeting = assessment_service.list_tasks_targeting_node(nodes["construct_cdf"])
        assert {t.id for t in targeting} == {t1.id, t2.id}

    def test_find_tasks_for_node_by_role(self, assessment_service, nodes):
        t1 = assessment_service.create_task(make_task(title="Primary task"))
        t2 = assessment_service.create_task(make_task(title="Secondary task", task_type=TaskType.DEBUGGING))
        assessment_service.add_target(t1.id, nodes["binary_search_cdf"], TargetRole.SECONDARY, 0.6)
        assessment_service.add_target(t2.id, nodes["binary_search_cdf"], TargetRole.PRIMARY, 1.0)

        primary = assessment_service.find_tasks_for_node(
            nodes["binary_search_cdf"], role=TargetRole.PRIMARY
        )
        assert [t.id for t in primary] == [t2.id]
        assert len(assessment_service.list_tasks_targeting_node(
            nodes["binary_search_cdf"], role=TargetRole.SECONDARY)) == 1

    def test_node_with_no_tasks(self, assessment_service, nodes):
        assert assessment_service.find_tasks_for_node(nodes["normalize_weights"]) == []


class TestSeedTask:
    @pytest.fixture()
    def seeded_task(self, assessment_service, repository):
        result = seed_weighted_sampling_task(
            assessment_service.task_repository,
            assessment_service.target_repository,
            repository,
        )
        task = assessment_service.get_task(uuid.UUID(result["task_id"]))
        return result, task, assessment_service

    def test_seed_task_fields(self, seeded_task):
        _, task, _ = seeded_task
        assert task.task_type == TASK_SPEC["task_type"]
        assert task.title == TASK_SPEC["title"]
        assert task.prompt == TASK_SPEC["prompt"]
        assert task.difficulty == 0.65

    def test_seed_has_eight_targets(self, seeded_task):
        result, task, service = seeded_task
        targets = service.list_targets_for_task(task.id)
        assert len(targets) == len(TARGET_SPECS) == 8

    def test_seed_target_roles_and_strengths(self, seeded_task):
        _, task, service = seeded_task
        targets = service.list_targets_for_task(task.id)
        by_slug = {}
        for t in targets:
            node = service.knowledge_repository.get_node(t.node_id)
            by_slug[node.slug] = (t.target_role, t.expected_signal_strength)

        expected = {
            "normalize_weights": (TargetRole.PRIMARY, 1.0),
            "construct_cdf": (TargetRole.PRIMARY, 1.0),
            "generate_uniform_sample": (TargetRole.PRIMARY, 0.9),
            "map_sample_to_interval": (TargetRole.PRIMARY, 1.0),
            "sampling_with_replacement": (TargetRole.PRIMARY, 0.9),
            "handle_boundaries": (TargetRole.DIAGNOSTIC, 0.7),
            "binary_search_cdf": (TargetRole.SECONDARY, 0.6),
            "analyze_sampling_complexity": (TargetRole.SECONDARY, 0.6),
        }
        assert by_slug == expected

    def test_seed_is_idempotent(self, seeded_task):
        result, task, service = seeded_task
        second = seed_weighted_sampling_task(
            service.task_repository, service.target_repository, service.knowledge_repository
        )
        assert second["task_created"] is False
        assert second["targets_created"] == 0
        assert len(service.list_tasks()) == 1

    def test_seed_task_targets_are_findable(self, seeded_task):
        result, task, service = seeded_task
        normalize = service.knowledge_repository.get_node_by_slug("normalize_weights")
        assert task.id in {t.id for t in service.find_tasks_for_node(normalize.id, role=TargetRole.PRIMARY)}