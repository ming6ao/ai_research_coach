"""Stage 5 tests: deterministic learner-state updates from evidence."""

from __future__ import annotations

import uuid

import pytest

from core.learning_partner.domain.evidence import Evidence, EvidenceType, ObservationStatus
from core.learning_partner.domain.learner import (
    Learner,
    LearnerKnowledgeState,
    StateStatus,
)
from core.learning_partner.domain.update import UpdateEngine, UpdateConfig
from core.learning_partner.seed import seed_weighted_sampling


@pytest.fixture()
def update_engine():
    return UpdateEngine()


@pytest.fixture()
def seeded_ctx(repository, learner_service):
    seed_weighted_sampling(repository)
    learner = learner_service.create_learner()
    return repository, learner_service, learner


def _neutral(learner, node_id) -> LearnerKnowledgeState:
    return LearnerKnowledgeState(
        learner_id=learner.id, node_id=node_id,
        mastery=0.5, uncertainty=1.0, evidence_count=0, status=StateStatus.UNKNOWN,
    )


def _evidence(learner, node_id, status, **kw) -> Evidence:
    defaults = dict(evidence_type=EvidenceType.ANSWER, observation_status=status)
    defaults.update(kw)
    return Evidence(learner_id=learner.id, node_id=node_id, **defaults)


class TestEvidenceMapping:
    def test_correct_base_performance(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        update = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.CORRECT, correctness=1.0)
        )
        assert update.base_performance == 1.0
        assert update.new_state.mastery > state.mastery

    def test_incorrect_base_performance(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        update = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.INCORRECT, correctness=0.0)
        )
        assert update.base_performance == 0.0
        assert update.new_state.mastery < state.mastery

    def test_partial_base_performance(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        update = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.PARTIALLY_CORRECT, correctness=0.5)
        )
        assert update.base_performance == 0.5

    def test_ambiguous_ignored(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        update = update_engine.apply(
            _neutral(learner, node_id),
            _evidence(learner, node_id, ObservationStatus.AMBIGUOUS),
        )
        assert update is None

    def test_not_observed_ignored(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        update = update_engine.apply(
            _neutral(learner, node_id),
            _evidence(learner, node_id, ObservationStatus.NOT_OBSERVED),
        )
        assert update is None


class TestUpdateBehavior:
    def test_first_correct_answer(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        update = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.CORRECT,
                             correctness=1.0, confidence=1.0, independence=1.0)
        )
        # 0.5 -> 0.7, not all the way to 1.0
        assert update.new_state.mastery == pytest.approx(0.7)
        assert update.new_state.uncertainty == pytest.approx(0.5)

    def test_first_incorrect_answer(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        update = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.INCORRECT,
                             correctness=0.0, confidence=1.0, independence=1.0)
        )
        assert update.new_state.mastery == pytest.approx(0.3)
        assert update.new_state.uncertainty == pytest.approx(0.5)

    def test_partial_answer(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        update = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.PARTIALLY_CORRECT,
                             correctness=0.5, confidence=1.0)
        )
        # mastery stays at neutral, but uncertainty drops (evidence was seen).
        assert update.new_state.mastery == pytest.approx(0.5)
        assert update.new_state.uncertainty < 1.0

    def test_repeated_correct_approaches_but_not_hits_1(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        for _ in range(5):
            state = update_engine.apply(
                state, _evidence(learner, node_id, ObservationStatus.CORRECT,
                                 correctness=1.0, confidence=1.0)
            ).new_state
        assert state.mastery < 1.0
        assert state.mastery > 0.95

    def test_single_observation_never_0_or_1(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        up = update_engine.apply(
            _neutral(learner, node_id),
            _evidence(learner, node_id, ObservationStatus.CORRECT, correctness=1.0, confidence=1.0)
        )
        assert 0 < up.new_state.mastery < 1
        down = update_engine.apply(
            _neutral(learner, node_id),
            _evidence(learner, node_id, ObservationStatus.INCORRECT, correctness=0.0, confidence=1.0)
        )
        assert 0 < down.new_state.mastery < 1

    def test_conflicting_evidence_pulls_back_toward_neutral(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        state = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.CORRECT, correctness=1.0, confidence=1.0)
        ).new_state
        up_mastery = state.mastery
        state = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.INCORRECT, correctness=0.0, confidence=1.0)
        ).new_state
        assert state.mastery < up_mastery
        assert 0 < state.mastery < 1

    def test_high_signal_vs_low_signal(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        high = update_engine.apply(
            _neutral(learner, node_id),
            _evidence(learner, node_id, ObservationStatus.CORRECT, correctness=1.0, confidence=1.0),
            expected_signal_strength=1.0,
        ).new_state
        low = update_engine.apply(
            _neutral(learner, node_id),
            _evidence(learner, node_id, ObservationStatus.CORRECT, correctness=1.0, confidence=1.0),
            expected_signal_strength=0.3,
        ).new_state
        assert high.mastery > low.mastery

    def test_uncertainty_reduces_with_evidence(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        for _ in range(3):
            state = update_engine.apply(
                state, _evidence(learner, node_id, ObservationStatus.CORRECT,
                                 correctness=1.0, confidence=1.0)
            ).new_state
        assert state.uncertainty < 0.3

    def test_evidence_quality_uses_only_observed_dims(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        # Only independence observed -> quality = independence.
        state = _neutral(learner, node_id)
        update = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.CORRECT,
                             correctness=1.0, independence=0.2)
        )
        # quality = 0.2; weight = 1.0 * 0.2; mastery 0.5 + 0.4*0.2*0.5 = 0.54
        assert update.new_state.mastery == pytest.approx(0.54)


class TestDimensionMapping:
    def test_explanation_updates_conceptual(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        up = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.CORRECT,
                             correctness=1.0, confidence=1.0, evidence_type=EvidenceType.EXPLANATION)
        ).new_state
        assert up.conceptual > 0.5
        assert up.procedural == pytest.approx(0.5)

    def test_code_updates_implementation_and_procedural(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        up = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.CORRECT,
                             correctness=1.0, confidence=1.0, evidence_type=EvidenceType.CODE)
        ).new_state
        assert up.implementation > 0.5
        assert up.procedural > 0.5
        assert up.conceptual == pytest.approx(0.5)

    def test_self_report_only_updates_self_confidence(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        up = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.CORRECT,
                             correctness=1.0, confidence=1.0, evidence_type=EvidenceType.SELF_REPORT)
        ).new_state
        assert up.self_confidence > 0.5
        assert up.mastery == pytest.approx(0.5)  # not performance evidence

    def test_conversation_is_low_strength(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        strong = update_engine.apply(
            _neutral(learner, node_id),
            _evidence(learner, node_id, ObservationStatus.CORRECT,
                      correctness=1.0, confidence=1.0, evidence_type=EvidenceType.CODE)
        ).new_state
        weak = update_engine.apply(
            _neutral(learner, node_id),
            _evidence(learner, node_id, ObservationStatus.CORRECT,
                      correctness=1.0, confidence=1.0, evidence_type=EvidenceType.CONVERSATION)
        ).new_state
        assert strong.mastery > weak.mastery


class TestStatusTransitions:
    def test_unknown_requires_zero_evidence(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        assert state.status == StateStatus.UNKNOWN

    def test_uncertain_after_first_evidence(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = update_engine.apply(
            _neutral(learner, node_id),
            _evidence(learner, node_id, ObservationStatus.CORRECT, correctness=1.0, confidence=1.0)
        ).new_state
        assert state.status == StateStatus.UNCERTAIN

    def test_proficient_after_two_strong_correct(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        for _ in range(2):
            state = update_engine.apply(
                state, _evidence(learner, node_id, ObservationStatus.CORRECT,
                                 correctness=1.0, confidence=1.0, independence=1.0)
            ).new_state
        assert state.status == StateStatus.PROFICIENT

    def test_mastered_after_three_strong_correct(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        for _ in range(3):
            state = update_engine.apply(
                state, _evidence(learner, node_id, ObservationStatus.CORRECT,
                                 correctness=1.0, confidence=1.0, independence=1.0)
            ).new_state
        assert state.status == StateStatus.MASTERED

    def test_developing_after_incorrect(self, update_engine, seeded_ctx):
        _, _, learner = seeded_ctx
        node_id = uuid.uuid4()
        state = update_engine.apply(
            _neutral(learner, node_id),
            _evidence(learner, node_id, ObservationStatus.INCORRECT, correctness=0.0, confidence=1.0)
        ).new_state
        # mastery 0.3, uncertainty 0.5 -> uncertain (uncertainty > 0.35)
        assert state.status == StateStatus.UNCERTAIN
        state = update_engine.apply(
            state, _evidence(learner, node_id, ObservationStatus.INCORRECT, correctness=0.0, confidence=1.0)
        ).new_state
        assert state.status == StateStatus.DEVELOPING

    def test_thresholds_configurable(self, seeded_ctx):
        _, _, learner = seeded_ctx
        cfg = UpdateConfig(mastered_mastery=0.6, mastered_uncertainty=0.4)
        eng = UpdateEngine(cfg)
        node_id = uuid.uuid4()
        state = _neutral(learner, node_id)
        for _ in range(2):
            state = eng.apply(
                state, _evidence(learner, node_id, ObservationStatus.CORRECT,
                                 correctness=1.0, confidence=1.0, independence=1.0)
            ).new_state
        # mastery 0.82, uncertainty 0.25 -> with relaxed config, mastered.
        assert state.status == StateStatus.MASTERED


class TestAuditAndPersistence:
    def test_service_persists_state_and_audit(self, learner_service, repository, update_repo, seeded_ctx):
        _, _, learner = seeded_ctx
        node = repository.get_node_by_slug("construct_cdf")
        ev = _evidence(learner, node.id, ObservationStatus.CORRECT,
                       correctness=1.0, confidence=1.0, evidence_type=EvidenceType.CODE)
        from core.learning_partner.services.update import LearnerUpdateService

        svc = LearnerUpdateService(
            learner_service._learners, repository, update_repo
        )
        update = svc.apply_evidence(ev)
        assert update is not None
        state = learner_service.get_state(learner.id, node.id)
        assert state.mastery == pytest.approx(update.new_state.mastery)
        assert state.evidence_count == 1

        records = update_repo.list_updates(learner_id=learner.id, node_id=node.id)
        assert len(records) == 1
        r = records[0]
        assert r.evidence_id == ev.id
        assert r.previous_mastery == 0.5
        assert r.new_mastery == state.mastery

    def test_ignored_evidence_no_audit(self, learner_service, repository, update_repo, seeded_ctx):
        _, _, learner = seeded_ctx
        node = repository.get_node_by_slug("construct_cdf")
        svc = learner_service
        from core.learning_partner.services.update import LearnerUpdateService

        usvc = LearnerUpdateService(svc._learners, repository, update_repo)
        result = usvc.apply_evidence(
            _evidence(learner, node.id, ObservationStatus.NOT_OBSERVED)
        )
        assert result is None
        assert update_repo.list_updates(learner_id=learner.id) == []