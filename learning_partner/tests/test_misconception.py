"""Stage 6 tests: learner misconceptions."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from learning_partner.domain.errors import (
    MisconceptionNotFoundError,
    NotMisconceptionNodeError,
)
from learning_partner.domain.knowledge import KnowledgeNode
from learning_partner.domain.misconception import (
    EvidenceRelationship,
    LearnerMisconception,
    MisconceptionStatus,
)
from learning_partner.domain.types import NodeType
from learning_partner.seed import seed_misconceptions, seed_weighted_sampling


@pytest.fixture()
def ctx(seeded_repository, learner_service, misconception_service, evidence_service):
    """Seed graph + misconception nodes; returns (services, learner, misconception node)."""
    seed_misconceptions(seeded_repository)
    learner = learner_service.create_learner()
    mc_node = seeded_repository.get_node_by_slug("cdf_is_normalized_weights")

    def make_evidence(status="incorrect"):
        from learning_partner.domain.evidence import Evidence, EvidenceType, ObservationStatus
        from learning_partner.domain.learner import Learner

        e_learner = learner_service.create_learner()
        ev = Evidence(
            learner_id=e_learner.id,
            node_id=mc_node.id,
            evidence_type=EvidenceType.ANSWER,
            observation_status=ObservationStatus(status),
            correctness=0.0 if status == "incorrect" else None,
        )
        return evidence_service.add_evidence(ev).id

    return {
        "repo": seeded_repository,
        "learner_service": learner_service,
        "mc_service": misconception_service,
        "evidence_service": evidence_service,
        "learner": learner,
        "mc_node": mc_node,
        "make_evidence": make_evidence,
    }


class TestCreation:
    def test_suspect_misconception_creates_suspected(self, ctx):
        mc = ctx["mc_service"].suspect_misconception(
            ctx["learner"].id, ctx["mc_node"].id, notes="CDF == normalized array"
        )
        assert mc.status == MisconceptionStatus.SUSPECTED
        assert mc.confidence > 0
        assert mc.learner_id == ctx["learner"].id
        assert mc.misconception_node_id == ctx["mc_node"].id

    def test_requires_misconception_node_type(self, ctx):
        concept = ctx["repo"].get_node_by_slug("probability")
        with pytest.raises(NotMisconceptionNodeError):
            ctx["mc_service"].suspect_misconception(ctx["learner"].id, concept.id)

    def test_requires_existing_learner(self, ctx):
        with pytest.raises(Exception):
            ctx["mc_service"].suspect_misconception(uuid.uuid4(), ctx["mc_node"].id)

    def test_suspect_is_idempotent(self, ctx):
        svc = ctx["mc_service"]
        first = svc.suspect_misconception(ctx["learner"].id, ctx["mc_node"].id)
        second = svc.suspect_misconception(ctx["learner"].id, ctx["mc_node"].id)
        assert first.id == second.id

    def test_incorrect_answer_does_not_create_misconception(self, ctx):
        """An incorrect answer alone must NOT create a misconception."""
        learner = ctx["learner_service"].create_learner()
        problem = ctx["repo"].get_node_by_slug("weighted_sampling_from_scratch")
        ctx["learner_service"].initialize_state(learner.id, problem.id)
        assert ctx["mc_service"].list_active_misconceptions(learner.id) == []


class TestConfidenceUpdates:
    def test_supporting_evidence_raises_confidence(self, ctx):
        svc = ctx["mc_service"]
        mc = svc.suspect_misconception(ctx["learner"].id, ctx["mc_node"].id)
        before = mc.confidence
        updated = svc.add_supporting_evidence(mc.id, ctx["make_evidence"]())
        assert updated.confidence > before

    def test_supporting_evidence_can_confirm(self, ctx):
        svc = ctx["mc_service"]
        mc = svc.suspect_misconception(ctx["learner"].id, ctx["mc_node"].id)
        for _ in range(5):
            mc = svc.add_supporting_evidence(mc.id, ctx["make_evidence"]())
        assert mc.status == MisconceptionStatus.CONFIRMED

    def test_contradicting_evidence_lowers_confidence(self, ctx):
        svc = ctx["mc_service"]
        mc = svc.suspect_misconception(ctx["learner"].id, ctx["mc_node"].id)
        before = mc.confidence
        updated = svc.add_contradicting_evidence(mc.id, ctx["make_evidence"]())
        assert updated.confidence < before

    def test_missing_misconception_raises(self, ctx):
        with pytest.raises(MisconceptionNotFoundError):
            ctx["mc_service"].add_supporting_evidence(uuid.uuid4(), uuid.uuid4())


class TestResolution:
    def test_resolve_marks_resolved(self, ctx):
        svc = ctx["mc_service"]
        mc = svc.suspect_misconception(ctx["learner"].id, ctx["mc_node"].id)
        resolved = svc.resolve_misconception(mc.id)
        assert resolved.status == MisconceptionStatus.RESOLVED
        assert resolved.resolved_at is not None

    def test_resolved_not_active(self, ctx):
        svc = ctx["mc_service"]
        mc = svc.suspect_misconception(ctx["learner"].id, ctx["mc_node"].id)
        svc.resolve_misconception(mc.id)
        active = svc.list_active_misconceptions(ctx["learner"].id)
        assert mc.id not in {m.id for m in active}


class TestEvidenceLinks:
    def test_evidence_links_are_recorded(self, ctx):
        svc = ctx["mc_service"]
        mc = svc.suspect_misconception(ctx["learner"].id, ctx["mc_node"].id)
        eid1, eid2 = ctx["make_evidence"](), ctx["make_evidence"]()
        svc.add_supporting_evidence(mc.id, eid1)
        svc.add_contradicting_evidence(mc.id, eid2)
        links = svc._misconceptions.list_evidence_links(mc.id)
        rels = {l.evidence_id: l.relationship for l in links}
        assert rels[eid1] == EvidenceRelationship.SUPPORTING
        assert rels[eid2] == EvidenceRelationship.CONTRADICTING


class TestModelValidation:
    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            LearnerMisconception(
                learner_id=uuid.uuid4(), misconception_node_id=uuid.uuid4(), bogus=True
            )