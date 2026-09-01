"""Learner model tests.

Uses the Weighted Sampling From Scratch seed graph so states reference real nodes.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from learning_partner.domain.errors import LearnerNotFoundError, NodeNotFoundError
from learning_partner.domain.knowledge import utcnow
from learning_partner.domain.learner import (
    LOW_MASTERY_THRESHOLD,
    UNKNOWN_DIMENSION,
    UNKNOWN_MASTERY,
    UNKNOWN_UNCERTAINTY,
    Learner,
    LearnerKnowledgeState,
    StateStatus,
)


@pytest.fixture()
def seeded(seeded_repository):
    return seeded_repository


@pytest.fixture()
def node_ids(seeded):
    """Returns {slug: node_id} for a few seed nodes."""
    return {
        "probability": seeded.get_node_by_slug("probability").id,
        "prefix_sum": seeded.get_node_by_slug("prefix_sum").id,
        "construct_cdf": seeded.get_node_by_slug("construct_cdf").id,
        "weighted_sampling_from_scratch": seeded.get_node_by_slug(
            "weighted_sampling_from_scratch"
        ).id,
    }


class TestLearner:
    def test_create_and_get_learner(self, learner_service):
        created = learner_service.create_learner()
        assert created.id is not None
        fetched = learner_service.get_learner(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.created_at == created.created_at

    def test_learner_metadata_roundtrip(self, learner_service):
        learner = Learner(metadata={"cohort": "alpha"})
        created = learner_service.create_learner(learner)
        assert learner_service.get_learner(created.id).metadata == {"cohort": "alpha"}

    def test_get_missing_learner_returns_none(self, learner_service):
        assert learner_service.get_learner(uuid.uuid4()) is None


class TestStateInitialization:
    def test_default_unknown_state(self, learner_service, node_ids):
        learner = learner_service.create_learner()
        state = learner_service.initialize_state(learner.id, node_ids["probability"])

        # Core semantic rule: unseen node = neutral prior, NOT low mastery.
        assert state.learner_id == learner.id
        assert state.node_id == node_ids["probability"]
        assert state.mastery == 0.5
        assert state.uncertainty == 1.0
        assert state.evidence_count == 0
        assert state.status == StateStatus.UNKNOWN
        assert state.conceptual == 0.5
        assert state.procedural == 0.5
        assert state.implementation == 0.5
        assert state.transfer == 0.5
        assert state.fluency == 0.5
        assert state.self_confidence == 0.5
        assert state.last_assessed_at is None
        assert state.last_decay_at is None

    def test_initialize_is_idempotent(self, learner_service, node_ids):
        learner = learner_service.create_learner()
        first = learner_service.initialize_state(learner.id, node_ids["prefix_sum"])
        second = learner_service.initialize_state(learner.id, node_ids["prefix_sum"])
        assert second.learner_id == first.learner_id
        assert second.node_id == first.node_id
        # Only one row for the (learner, node) pair.
        assert len(learner_service.list_learner_states(learner.id)) == 1

    def test_initialize_requires_existing_node(self, learner_service):
        learner = learner_service.create_learner()
        with pytest.raises(NodeNotFoundError):
            learner_service.initialize_state(learner.id, uuid.uuid4())

    def test_initialize_requires_existing_learner(self, learner_service, node_ids):
        with pytest.raises(LearnerNotFoundError):
            learner_service.initialize_state(uuid.uuid4(), node_ids["probability"])

    def test_no_auto_state_for_whole_graph(self, learner_service, seeded):
        # Creating a learner must NOT create state for every node in the graph.
        learner = learner_service.create_learner()
        assert learner_service.list_learner_states(learner.id) == []


class TestStateRetrieval:
    def test_get_state_returns_none_before_initialization(self, learner_service, node_ids):
        learner = learner_service.create_learner()
        assert learner_service.get_state(learner.id, node_ids["probability"]) is None

    def test_get_state_after_initialization(self, learner_service, node_ids):
        learner = learner_service.create_learner()
        learner_service.initialize_state(learner.id, node_ids["probability"])
        state = learner_service.get_state(learner.id, node_ids["probability"])
        assert state is not None
        assert state.status == StateStatus.UNKNOWN


class TestUpsert:
    def test_upsert_inserts_new_state(self, learner_service, node_ids):
        learner = learner_service.create_learner()
        state = learner_service.upsert_state(
            LearnerKnowledgeState(
                learner_id=learner.id,
                node_id=node_ids["construct_cdf"],
                mastery=0.3,
                uncertainty=0.2,
                evidence_count=3,
                status=StateStatus.DEVELOPING,
            )
        )
        assert state.mastery == 0.3
        assert state.status == StateStatus.DEVELOPING
        assert learner_service.get_state(learner.id, node_ids["construct_cdf"]) is not None

    def test_upsert_updates_existing_state(self, learner_service, node_ids):
        learner = learner_service.create_learner()
        learner_service.upsert_state(
            LearnerKnowledgeState(
                learner_id=learner.id,
                node_id=node_ids["construct_cdf"],
                mastery=0.3,
                uncertainty=0.2,
                evidence_count=3,
                status=StateStatus.DEVELOPING,
            )
        )
        updated = learner_service.upsert_state(
            LearnerKnowledgeState(
                learner_id=learner.id,
                node_id=node_ids["construct_cdf"],
                mastery=0.9,
                uncertainty=0.1,
                evidence_count=7,
                status=StateStatus.MASTERED,
            )
        )
        assert updated.mastery == 0.9
        assert updated.status == StateStatus.MASTERED
        assert updated.evidence_count == 7
        # Still exactly one row.
        assert len(learner_service.list_learner_states(learner.id)) == 1

    def test_upsert_updates_updated_at(self, learner_service, node_ids):
        learner = learner_service.create_learner()
        first = learner_service.upsert_state(
            LearnerKnowledgeState(
                learner_id=learner.id,
                node_id=node_ids["construct_cdf"],
                mastery=0.3,
                uncertainty=0.2,
                evidence_count=3,
                status=StateStatus.DEVELOPING,
            )
        )
        second = learner_service.upsert_state(
            LearnerKnowledgeState(
                learner_id=learner.id,
                node_id=node_ids["construct_cdf"],
                mastery=0.6,
                uncertainty=0.1,
                evidence_count=4,
                status=StateStatus.PROFICIENT,
            )
        )
        assert second.updated_at >= first.updated_at

    def test_upsert_requires_learner(self, learner_service, node_ids):
        with pytest.raises(LearnerNotFoundError):
            learner_service.upsert_state(
                LearnerKnowledgeState(
                    learner_id=uuid.uuid4(),
                    node_id=node_ids["probability"],
                    mastery=0.5,
                    uncertainty=0.2,
                    evidence_count=1,
                    status=StateStatus.UNCERTAIN,
                )
            )

    def test_upsert_requires_node(self, learner_service):
        learner = learner_service.create_learner()
        with pytest.raises(NodeNotFoundError):
            learner_service.upsert_state(
                LearnerKnowledgeState(
                    learner_id=learner.id,
                    node_id=uuid.uuid4(),
                    mastery=0.5,
                    uncertainty=0.2,
                    evidence_count=1,
                    status=StateStatus.UNCERTAIN,
                )
            )


class TestIndependence:
    def test_multiple_learners_have_independent_state(self, learner_service, node_ids):
        a = learner_service.create_learner()
        b = learner_service.create_learner()
        learner_service.initialize_state(a.id, node_ids["probability"])
        learner_service.initialize_state(b.id, node_ids["probability"])

        assert learner_service.get_state(a.id, node_ids["probability"]) is not None
        assert learner_service.get_state(b.id, node_ids["probability"]) is not None

    def test_same_node_different_mastery_per_learner(self, learner_service, node_ids):
        a = learner_service.create_learner()
        b = learner_service.create_learner()
        nid = node_ids["prefix_sum"]

        learner_service.upsert_state(
            LearnerKnowledgeState(
                learner_id=a.id, node_id=nid,
                mastery=0.9, uncertainty=0.1, evidence_count=5, status=StateStatus.MASTERED,
            )
        )
        learner_service.upsert_state(
            LearnerKnowledgeState(
                learner_id=b.id, node_id=nid,
                mastery=0.3, uncertainty=0.2, evidence_count=2, status=StateStatus.DEVELOPING,
            )
        )

        assert learner_service.get_state(a.id, nid).mastery == 0.9
        assert learner_service.get_state(b.id, nid).mastery == 0.3
        assert learner_service.get_state(a.id, nid).status == StateStatus.MASTERED
        assert learner_service.get_state(b.id, nid).status == StateStatus.DEVELOPING

    def test_lists_are_per_learner(self, learner_service, node_ids):
        a = learner_service.create_learner()
        b = learner_service.create_learner()
        for lid in (a.id, b.id):
            learner_service.initialize_state(lid, node_ids["probability"])
        learner_service.upsert_state(
            LearnerKnowledgeState(
                learner_id=a.id, node_id=node_ids["prefix_sum"],
                mastery=0.9, uncertainty=0.1, evidence_count=5, status=StateStatus.MASTERED,
            )
        )
        assert [s.node_id for s in learner_service.list_mastered_nodes(a.id)] == [node_ids["prefix_sum"]]
        assert learner_service.list_mastered_nodes(b.id) == []


class TestLists:
    def _seed_states(self, learner_service, learner, node_ids):
        """probability: unknown; prefix_sum: mastered; construct_cdf: developing(low)."""
        learner_service.initialize_state(learner.id, node_ids["probability"])
        learner_service.upsert_state(
            LearnerKnowledgeState(
                learner_id=learner.id, node_id=node_ids["prefix_sum"],
                mastery=0.9, uncertainty=0.1, evidence_count=5, status=StateStatus.MASTERED,
            )
        )
        learner_service.upsert_state(
            LearnerKnowledgeState(
                learner_id=learner.id, node_id=node_ids["construct_cdf"],
                mastery=0.2, uncertainty=0.2, evidence_count=2, status=StateStatus.DEVELOPING,
            )
        )

    def test_list_learner_states(self, learner_service, node_ids):
        learner = learner_service.create_learner()
        self._seed_states(learner_service, learner, node_ids)
        states = learner_service.list_learner_states(learner.id)
        assert len(states) == 3
        assert {s.node_id for s in states} == {
            node_ids["probability"],
            node_ids["prefix_sum"],
            node_ids["construct_cdf"],
        }

    def test_list_uncertain_nodes_includes_unknown_but_not_mastered(
        self, learner_service, node_ids
    ):
        learner = learner_service.create_learner()
        self._seed_states(learner_service, learner, node_ids)
        uncertain = learner_service.list_uncertain_nodes(learner.id)
        # Only probability is unknown/uncertain; prefix_sum is mastered,
        # construct_cdf is developing (no longer "uncertain").
        assert {s.node_id for s in uncertain} == {node_ids["probability"]}

    def test_list_low_mastery_nodes_excludes_unknown(self, learner_service, node_ids):
        learner = learner_service.create_learner()
        self._seed_states(learner_service, learner, node_ids)
        low = learner_service.list_low_mastery_nodes(learner.id)
        # construct_cdf (mastery 0.2) is low; unknown probability (mastery 0.5) is NOT.
        assert {s.node_id for s in low} == {node_ids["construct_cdf"]}

    def test_list_mastered_nodes(self, learner_service, node_ids):
        learner = learner_service.create_learner()
        self._seed_states(learner_service, learner, node_ids)
        mastered = learner_service.list_mastered_nodes(learner.id)
        assert {s.node_id for s in mastered} == {node_ids["prefix_sum"]}


class TestScoreValidation:
    def test_scores_must_be_in_0_1(self):
        with pytest.raises(ValidationError):
            LearnerKnowledgeState(learner_id=uuid.uuid4(), node_id=uuid.uuid4(), mastery=1.2)
        with pytest.raises(ValidationError):
            LearnerKnowledgeState(learner_id=uuid.uuid4(), node_id=uuid.uuid4(), uncertainty=-0.1)
        with pytest.raises(ValidationError):
            LearnerKnowledgeState(learner_id=uuid.uuid4(), node_id=uuid.uuid4(), conceptual=2.0)
        with pytest.raises(ValidationError):
            LearnerKnowledgeState(learner_id=uuid.uuid4(), node_id=uuid.uuid4(), fluency=0.0 - 1e-9)

    def test_boundary_values_allowed(self):
        s = LearnerKnowledgeState(
            learner_id=uuid.uuid4(), node_id=uuid.uuid4(),
            mastery=0.0, uncertainty=0.0, conceptual=1.0, procedural=1.0,
            implementation=1.0, transfer=1.0, fluency=1.0, self_confidence=0.0,
            evidence_count=1, status=StateStatus.UNCERTAIN,
        )
        assert s.mastery == 0.0

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            LearnerKnowledgeState(
                learner_id=uuid.uuid4(), node_id=uuid.uuid4(), bogus=True
            )

    def test_unknown_requires_zero_evidence(self):
        with pytest.raises(ValidationError):
            LearnerKnowledgeState(
                learner_id=uuid.uuid4(), node_id=uuid.uuid4(),
                mastery=0.5, uncertainty=1.0, evidence_count=1, status=StateStatus.UNKNOWN,
            )

    def test_unknown_requires_neutral_mastery(self):
        with pytest.raises(ValidationError):
            LearnerKnowledgeState(
                learner_id=uuid.uuid4(), node_id=uuid.uuid4(),
                mastery=0.1, uncertainty=1.0, evidence_count=0, status=StateStatus.UNKNOWN,
            )


class TestDerivedHelpers:
    def test_unknown_state_helpers(self, learner_service, node_ids):
        learner = learner_service.create_learner()
        state = learner_service.initialize_state(learner.id, node_ids["probability"])
        assert state.is_unknown() is True
        assert state.is_uncertain() is True
        assert state.is_mastered() is False
        assert state.is_low_mastery() is False
        assert state.is_ready_for_assessment() is True
        assert state.confidence_level() == 0.0  # 1.0 - uncertainty

    def test_uncertain_state_helpers(self):
        state = LearnerKnowledgeState(
            learner_id=uuid.uuid4(), node_id=uuid.uuid4(),
            mastery=0.5, uncertainty=0.7, evidence_count=2, status=StateStatus.UNCERTAIN,
        )
        assert state.is_uncertain() is True
        assert state.is_unknown() is False
        assert state.is_ready_for_assessment() is True
        assert state.confidence_level() == pytest.approx(0.3)

    def test_developing_low_mastery_helpers(self):
        state = LearnerKnowledgeState(
            learner_id=uuid.uuid4(), node_id=uuid.uuid4(),
            mastery=0.2, uncertainty=0.2, evidence_count=2, status=StateStatus.DEVELOPING,
        )
        assert state.is_low_mastery() is True
        assert state.is_ready_for_assessment() is False

    def test_mastered_helpers(self):
        state = LearnerKnowledgeState(
            learner_id=uuid.uuid4(), node_id=uuid.uuid4(),
            mastery=0.95, uncertainty=0.05, evidence_count=10, status=StateStatus.MASTERED,
        )
        assert state.is_mastered() is True
        assert state.is_ready_for_assessment() is False
        assert state.confidence_level() == 0.95

    def test_derive_status_buckets(self):
        assert LearnerKnowledgeState.derive_status(0, 0.5, 1.0) == StateStatus.UNKNOWN
        assert LearnerKnowledgeState.derive_status(1, 0.5, 0.8) == StateStatus.UNCERTAIN
        assert LearnerKnowledgeState.derive_status(2, 0.3, 0.2) == StateStatus.DEVELOPING
        assert LearnerKnowledgeState.derive_status(2, 0.7, 0.2) == StateStatus.PROFICIENT
        assert LearnerKnowledgeState.derive_status(5, 0.95, 0.1) == StateStatus.MASTERED

    def test_unknown_mastery_equals_low_mastery_threshold(self):
        # The neutral prior is exactly the threshold, so unknown is never "low".
        assert UNKNOWN_MASTERY == LOW_MASTERY_THRESHOLD