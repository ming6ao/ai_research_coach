"""Evidence tests: immutability, filtering, aggregation, and the critical
incorrect-vs-not_observed distinction."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from core.learning_partner.domain.errors import (
    DuplicateEvidenceError,
    LearnerNotFoundError,
    NodeNotFoundError,
)
from core.learning_partner.domain.evidence import (
    Evidence,
    EvidenceFilter,
    EvidenceType,
    ObservationStatus,
)
from core.learning_partner.domain.knowledge import utcnow
from core.learning_partner.domain.learner import Learner
from core.learning_partner.seed import seed_weighted_sampling


@pytest.fixture()
def seeded_ctx(evidence_service, repository):
    """Seed the graph and create a learner; returns (evidence_service, learner, node)."""
    seed_weighted_sampling(repository)
    learner = evidence_service.learner_repository.create_learner(Learner())
    problem = repository.get_node_by_slug("weighted_sampling_from_scratch")
    return evidence_service, learner, problem


def make_evidence(learner_id, node_id, **overrides):
    status = overrides.get("observation_status", ObservationStatus.CORRECT)
    defaults = dict(
        learner_id=learner_id,
        node_id=node_id,
        evidence_type=EvidenceType.ANSWER,
        observation_status=status,
        reasoning_quality=0.8,
        confidence=0.9,
    )
    # not_observed records must not carry a correctness score.
    if status != ObservationStatus.NOT_OBSERVED:
        defaults["correctness"] = 1.0
    defaults.update(overrides)
    return Evidence(**defaults)


class TestImmutability:
    def test_model_is_frozen(self):
        ev = Evidence(
            learner_id=uuid.uuid4(),
            node_id=uuid.uuid4(),
            evidence_type=EvidenceType.ANSWER,
            observation_status=ObservationStatus.CORRECT,
        )
        with pytest.raises(ValidationError):
            ev.correctness = 0.5  # type: ignore[misc]
        with pytest.raises(ValidationError):
            ev.observation_status = ObservationStatus.INCORRECT  # type: ignore[misc]

    def test_repository_is_append_only(self, evidence_repository):
        # No update/delete surface exists on the repository.
        assert not hasattr(evidence_repository, "update_evidence")
        assert not hasattr(evidence_repository, "delete_evidence")

    def test_duplicate_add_rejected(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        record = make_evidence(learner.id, problem.id)
        service.add_evidence(record)
        with pytest.raises(DuplicateEvidenceError):
            service.add_evidence(record)

    def test_add_requires_existing_learner_and_node(self, evidence_service, seeded_ctx):
        service, _, problem = seeded_ctx
        with pytest.raises(LearnerNotFoundError):
            service.add_evidence(make_evidence(uuid.uuid4(), problem.id))
        learner = service.learner_repository.create_learner(Learner())
        with pytest.raises(NodeNotFoundError):
            service.add_evidence(make_evidence(learner.id, uuid.uuid4()))


class TestCRUD:
    def test_add_and_get(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        record = make_evidence(learner.id, problem.id)
        stored = service.add_evidence(record)
        assert stored.id == record.id
        assert service.get_evidence(record.id) == stored

    def test_get_missing_returns_none(self, evidence_service):
        assert evidence_service.get_evidence(uuid.uuid4()) is None

    def test_list_for_learner(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        service.add_evidence(make_evidence(learner.id, problem.id))
        other = service.learner_repository.create_learner(Learner())
        service.add_evidence(make_evidence(other.id, problem.id))

        rows = service.list_evidence_for_learner(learner.id)
        assert len(rows) == 1
        assert rows[0].learner_id == learner.id

    def test_list_for_node(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        cdf =  service.knowledge_repository.get_node_by_slug("construct_cdf")
        service.add_evidence(make_evidence(learner.id, problem.id))
        service.add_evidence(make_evidence(learner.id, cdf.id))

        rows = service.list_evidence_for_node(cdf.id)
        assert len(rows) == 1
        assert rows[0].node_id == cdf.id

    def test_list_for_interaction(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        interaction = uuid.uuid4()
        service.add_evidence(
            make_evidence(learner.id, problem.id, interaction_id=interaction)
        )
        service.add_evidence(make_evidence(learner.id, problem.id))
        rows = service.list_evidence_for_interaction(interaction)
        assert len(rows) == 1
        assert rows[0].interaction_id == interaction

    def test_count_and_latest(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        t0 = datetime.now(timezone.utc) - timedelta(days=1)
        e1 = service.add_evidence(make_evidence(learner.id, problem.id, created_at=t0))
        e2 = service.add_evidence(
            make_evidence(learner.id, problem.id, created_at=utcnow())
        )
        assert service.count_evidence() == 2
        assert service.get_latest_evidence().id == e2.id
        assert service.get_latest_evidence(
            EvidenceFilter(observation_status=ObservationStatus.CORRECT)
        ).id == e2.id


class TestFiltering:
    def test_filter_by_type(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        service.add_evidence(
            make_evidence(learner.id, problem.id, evidence_type=EvidenceType.ANSWER)
        )
        service.add_evidence(
            make_evidence(learner.id, problem.id, evidence_type=EvidenceType.CODE)
        )
        assert service.count_evidence(EvidenceFilter(evidence_type=EvidenceType.CODE)) == 1

    def test_filter_by_status(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        service.add_evidence(
            make_evidence(learner.id, problem.id, observation_status=ObservationStatus.CORRECT)
        )
        service.add_evidence(
            make_evidence(learner.id, problem.id, observation_status=ObservationStatus.INCORRECT, correctness=0.0)
        )
        assert service.count_evidence(
            EvidenceFilter(observation_status=ObservationStatus.INCORRECT)
        ) == 1

    def test_filter_by_time_range(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        service.add_evidence(
            make_evidence(learner.id, problem.id, created_at=base + timedelta(days=1))
        )
        service.add_evidence(
            make_evidence(learner.id, problem.id, created_at=base + timedelta(days=5))
        )
        f = EvidenceFilter(
            from_time=base + timedelta(days=2),
            to_time=base + timedelta(days=6),
        )
        assert service.count_evidence(f) == 1

    def test_combined_filters(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        service.add_evidence(
            make_evidence(learner.id, problem.id, evidence_type=EvidenceType.ANSWER,
                          observation_status=ObservationStatus.CORRECT)
        )
        service.add_evidence(
            make_evidence(learner.id, problem.id, evidence_type=EvidenceType.CODE,
                          observation_status=ObservationStatus.CORRECT)
        )
        f = EvidenceFilter(evidence_type=EvidenceType.CODE, observation_status=ObservationStatus.CORRECT)
        assert service.count_evidence(f) == 1


class TestSummaryAggregation:
    def test_summary_counts(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        service.add_evidence(make_evidence(learner.id, problem.id, observation_status=ObservationStatus.CORRECT, correctness=1.0))
        service.add_evidence(make_evidence(learner.id, problem.id, observation_status=ObservationStatus.INCORRECT, correctness=0.0))
        service.add_evidence(make_evidence(learner.id, problem.id, observation_status=ObservationStatus.PARTIALLY_CORRECT, correctness=0.5))
        service.add_evidence(make_evidence(learner.id, problem.id, observation_status=ObservationStatus.AMBIGUOUS))
        service.add_evidence(
            make_evidence(learner.id, problem.id, observation_status=ObservationStatus.NOT_OBSERVED)
        )

        summary = service.summarize(learner.id, problem.id)
        assert summary.observation_count == 5
        assert summary.correct_count == 1
        assert summary.incorrect_count == 1
        assert summary.partial_count == 1
        assert summary.ambiguous_count == 1
        assert summary.not_observed_count == 1

    def test_average_correctness(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        service.add_evidence(make_evidence(learner.id, problem.id, observation_status=ObservationStatus.CORRECT, correctness=1.0))
        service.add_evidence(make_evidence(learner.id, problem.id, observation_status=ObservationStatus.INCORRECT, correctness=0.0))
        service.add_evidence(make_evidence(learner.id, problem.id, observation_status=ObservationStatus.PARTIALLY_CORRECT, correctness=0.5))
        summary = service.summarize(learner.id, problem.id)
        assert summary.average_correctness == pytest.approx(0.5)

    def test_average_reasoning_quality(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        service.add_evidence(make_evidence(learner.id, problem.id, reasoning_quality=0.8))
        service.add_evidence(make_evidence(learner.id, problem.id, reasoning_quality=0.4))
        summary = service.summarize(learner.id, problem.id)
        assert summary.average_reasoning_quality == pytest.approx(0.6)

    def test_summary_empty(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        summary = service.summarize(learner.id, problem.id)
        assert summary.observation_count == 0
        assert summary.average_correctness is None
        assert summary.latest_observation is None
        assert summary.latest_confidence is None

    def test_summary_latest_and_confidence(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        old = service.add_evidence(make_evidence(learner.id, problem.id, confidence=0.7))
        new = service.add_evidence(make_evidence(learner.id, problem.id, confidence=0.95))
        summary = service.summarize(learner.id, problem.id)
        assert summary.latest_observation.id == new.id
        assert summary.latest_confidence == 0.95

    def test_summary_latest_confidence_skips_none(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        service.add_evidence(make_evidence(learner.id, problem.id, confidence=None))
        service.add_evidence(make_evidence(learner.id, problem.id, confidence=0.8))
        service.add_evidence(make_evidence(learner.id, problem.id, confidence=None))
        summary = service.summarize(learner.id, problem.id)
        assert summary.latest_confidence == 0.8


class TestNotObservedVsIncorrect:
    """The critical distinction: not_observed is never incorrect."""

    def test_not_observed_cannot_carry_correctness(self):
        with pytest.raises(ValidationError):
            Evidence(
                learner_id=uuid.uuid4(),
                node_id=uuid.uuid4(),
                evidence_type=EvidenceType.ANSWER,
                observation_status=ObservationStatus.NOT_OBSERVED,
                correctness=0.0,
            )

    def test_status_helpers_are_disjoint(self):
        not_observed = Evidence(
            learner_id=uuid.uuid4(), node_id=uuid.uuid4(),
            evidence_type=EvidenceType.ANSWER,
            observation_status=ObservationStatus.NOT_OBSERVED,
        )
        assert not_observed.is_not_observed() is True
        assert not_observed.is_incorrect() is False
        assert not_observed.is_correct() is False
        assert not_observed.is_partially_correct() is False
        assert not_observed.is_ambiguous() is False

        incorrect = Evidence(
            learner_id=uuid.uuid4(), node_id=uuid.uuid4(),
            evidence_type=EvidenceType.ANSWER,
            observation_status=ObservationStatus.INCORRECT,
            correctness=0.0,
        )
        assert incorrect.is_incorrect() is True
        assert incorrect.is_not_observed() is False

    def test_summary_does_not_count_not_observed_as_incorrect(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        # 3 not_observed records, no incorrect records.
        for _ in range(3):
            service.add_evidence(
                make_evidence(learner.id, problem.id, observation_status=ObservationStatus.NOT_OBSERVED)
            )
        summary = service.summarize(learner.id, problem.id)
        assert summary.not_observed_count == 3
        assert summary.incorrect_count == 0
        # Averages are undefined (no scored observations).
        assert summary.average_correctness is None

    def test_summary_mixed_not_observed_and_incorrect(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        service.add_evidence(
            make_evidence(learner.id, problem.id, observation_status=ObservationStatus.INCORRECT, correctness=0.0)
        )
        service.add_evidence(
            make_evidence(learner.id, problem.id, observation_status=ObservationStatus.NOT_OBSERVED)
        )
        summary = service.summarize(learner.id, problem.id)
        assert summary.incorrect_count == 1
        assert summary.not_observed_count == 1
        # Correctness average ignores the not_observed record.
        assert summary.average_correctness == pytest.approx(0.0)

    def test_filter_can_isolate_not_observed(self, seeded_ctx):
        service, learner, problem = seeded_ctx
        service.add_evidence(make_evidence(learner.id, problem.id, observation_status=ObservationStatus.INCORRECT, correctness=0.0))
        service.add_evidence(make_evidence(learner.id, problem.id, observation_status=ObservationStatus.NOT_OBSERVED))
        not_observed = service.list_evidence_for_learner(
            learner.id, EvidenceFilter(observation_status=ObservationStatus.NOT_OBSERVED)
        )
        assert len(not_observed) == 1
        assert not_observed[0].is_not_observed()


class TestSampleEvidence:
    def test_weighted_sampling_evidence_record(self, seeded_ctx):
        """A representative evidence record for the weighted-sampling problem."""
        service, learner, problem = seeded_ctx
        record = Evidence(
            learner_id=learner.id,
            session_id=uuid.uuid4(),
            interaction_id=uuid.uuid4(),
            assessment_task_id=uuid.uuid4(),
            node_id=problem.id,
            evidence_type=EvidenceType.CODE,
            observation_status=ObservationStatus.PARTIALLY_CORRECT,
            correctness=0.5,
            reasoning_quality=0.6,
            independence=0.7,
            confidence=0.6,
            observed_behavior="Normalized the weights but sampled with a linear scan that "
                              "mis-mapped the first CDF bucket.",
            assessor_explanation="The learner built the CDF correctly but applied an off-by-one "
                                 "interval check, so boundary samples landed in the wrong bucket.",
            assessment_payload={
                "language": "python",
                "submitted_snippet": "while cum < u: ...",
                "time_seconds": 612,
            },
        )
        stored = service.add_evidence(record)
        assert stored.id == record.id
        summary = service.summarize(learner.id, problem.id)
        assert summary.observation_count == 1
        assert summary.partial_count == 1
        assert summary.incorrect_count == 0
        assert summary.average_correctness == 0.5
        assert summary.latest_observation.id == record.id