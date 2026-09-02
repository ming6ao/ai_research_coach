"""Stage 9 tests: end-to-end adaptive learning loop via the orchestrator."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.learning_partner.container import build_container
from core.learning_partner.domain.learner import StateStatus
from core.learning_partner.domain.orchestrator import LearnerInteraction
from core.learning_partner.seed import (
    seed_misconceptions,
    seed_weighted_sampling,
    seed_weighted_sampling_task,
)
from core.learning_partner.services.assessors import RuleBasedEvidenceAssessor
from core.learning_partner.services.orchestrator import LearningOrchestrator
from core.learning_partner.storage.database import Base


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        yield s
    engine.dispose()


@pytest.fixture()
def world(session):
    """Fully seeded world (graph + task + misconceptions) + orchestrator."""
    c = build_container(session)
    seed_weighted_sampling(c.knowledge_repository)
    seed_weighted_sampling_task(c.task_repository, c.target_repository, c.knowledge_repository)
    seed_misconceptions(c.knowledge_repository)

    learner = c.learner_service.create_learner()
    problem = c.knowledge_repository.get_node_by_slug("weighted_sampling_from_scratch")

    resolver = lambda slug: (  # noqa: E731
    c.knowledge_repository.get_node_by_slug(slug).id
    if c.knowledge_repository.get_node_by_slug(slug) else None
)
    assessor = RuleBasedEvidenceAssessor(rules=RULES, node_resolver=resolver)
    orchestrator = LearningOrchestrator(c, assessor)
    return {
        "c": c,
        "learner": learner,
        "problem": problem,
        "orchestrator": orchestrator,
    }


RULES = [
    # Interaction 1: learner correctly explains normalization and CDF.
    {
        "keywords": ["normalize", "cdf"],
        "node_slug": "normalize_weights",
        "evidence_type": "explanation",
        "observation_status": "correct",
        "correctness": 1.0, "confidence": 1.0, "independence": 1.0,
        "reasoning_quality": 1.0,
    },
    {
        "keywords": ["normalize", "cdf"],
        "node_slug": "construct_cdf",
        "evidence_type": "explanation",
        "observation_status": "correct",
        "correctness": 1.0, "confidence": 1.0, "independence": 1.0,
        "reasoning_quality": 1.0,
    },
    # Interaction 2: correct linear-scan implementation (not binary search).
    {
        "keywords": ["linear"],
        "node_slug": "normalize_weights",
        "evidence_type": "code",
        "observation_status": "correct",
        "correctness": 1.0, "confidence": 1.0, "independence": 1.0,
    },
    {
        "keywords": ["linear"],
        "node_slug": "construct_cdf",
        "evidence_type": "code",
        "observation_status": "correct",
        "correctness": 1.0, "confidence": 1.0, "independence": 1.0,
    },
    {
        "keywords": ["linear"],
        "node_slug": "map_sample_to_interval",
        "evidence_type": "code",
        "observation_status": "correct",
        "correctness": 1.0, "confidence": 1.0, "independence": 1.0,
    },
    # Interaction 3: how to optimize repeated sampling (complexity, partial).
    {
        "keywords": ["optimize"],
        "node_slug": "analyze_sampling_complexity",
        "evidence_type": "prediction",
        "observation_status": "partially_correct",
        "correctness": 0.5, "confidence": 0.5, "reasoning_quality": 0.6,
    },
    # Interaction 4: cumulative-boundary mistake -> incorrect boundary handling
    # plus a supporting diagnostic evidence for the CDF misconception.
    {
        "keywords": ["boundary"],
        "node_slug": "handle_boundaries",
        "evidence_type": "code",
        "observation_status": "incorrect",
        "correctness": 0.0, "confidence": 0.8, "independence": 0.8,
    },
    {
        "keywords": ["boundary"],
        "node_slug": "cdf_is_normalized_weights",
        "evidence_type": "debugging",
        "observation_status": "incorrect",
        "assessment_payload": {
            "misconception_node_slug": "cdf_is_normalized_weights",
            "relationship": "supporting",
        },
    },
]


def _interaction(world, message, index):
    c = world["c"]
    return LearnerInteraction(
        learner_id=world["learner"].id,
        session_id=uuid.uuid4(),
        interaction_id=uuid.uuid4(),
        topic_node_id=world["problem"].id,
        assessment_task_id=c.task_repository.list_tasks()[0].id,
        message=message,
    )


class TestEndToEndLoop:
    def test_full_session_evolves_learner(self, world):
        c = world["c"]
        orch = world["orchestrator"]

        r1 = orch.process(_interaction(world, "I normalize the weights and build the CDF.", 1))
        r2 = orch.process(_interaction(world, "I wrote a correct linear-scan implementation.", 2))
        r3 = orch.process(_interaction(world, "To optimize repeated sampling I'd binary search.", 3))
        r4 = orch.process(_interaction(world, "I get the cumulative boundary wrong at the first bucket.", 4))

        states = {s.node_id: s for s in c.learner_service.list_learner_states(world["learner"].id)}
        def slug_state(slug):
            return states[c.knowledge_repository.get_node_by_slug(slug).id]

        normalize = slug_state("normalize_weights")
        cdf = slug_state("construct_cdf")
        impl = slug_state("map_sample_to_interval")
        binary = c.learner_service.get_state(
            world["learner"].id, c.knowledge_repository.get_node_by_slug("binary_search_cdf").id
        )
        complexity = slug_state("analyze_sampling_complexity")
        boundary = slug_state("handle_boundaries")

        # normalization becomes proficient
        assert normalize.mastery >= 0.7 and normalize.status == StateStatus.PROFICIENT
        # CDF becomes proficient
        assert cdf.mastery >= 0.7 and cdf.status == StateStatus.PROFICIENT
        # implementation dimension strengthened on map_sample_to_interval
        assert impl.implementation > 0.5
        assert impl.evidence_count >= 1
        # binary search initially remains uncertain / not confirmed
        assert binary is None or binary.status in (StateStatus.UNKNOWN, StateStatus.UNCERTAIN)
        # complexity becomes partially evidenced (evidence seen, still uncertain)
        assert complexity.evidence_count >= 1
        assert complexity.status == StateStatus.UNCERTAIN
        # boundary handling weakens / remains uncertain
        assert boundary.mastery < 0.5
        assert boundary.status == StateStatus.UNCERTAIN

    def test_frontier_changes_toward_gaps(self, world):
        orch = world["orchestrator"]
        for i, msg in enumerate([
            "I normalize the weights and build the CDF.",
            "I wrote a correct linear-scan implementation.",
            "To optimize repeated sampling I'd binary search.",
            "I get the cumulative boundary wrong at the first bucket.",
        ]):
            orch.process(_interaction(world, msg, i))

        c = world["c"]
        frontier = c.frontier_service.list_frontier(world["learner"].id)
        by_node = {f.node_id: f.priority for f in frontier}

        normalize = c.knowledge_repository.get_node_by_slug("normalize_weights").id
        cdf = c.knowledge_repository.get_node_by_slug("construct_cdf").id
        boundary = c.knowledge_repository.get_node_by_slug("handle_boundaries").id
        complexity = c.knowledge_repository.get_node_by_slug("analyze_sampling_complexity").id
        binary = c.knowledge_repository.get_node_by_slug("binary_search_cdf").id

        # Remaining gaps are on the frontier with nonzero priority.
        assert by_node.get(boundary, 0) > 0
        assert by_node.get(complexity, 0) > 0
        assert by_node.get(binary, 0) > 0
        # Strong skills are not prioritized above the gaps (low uncertainty).
        assert by_node.get(normalize, 1) <= by_node.get(boundary, 0)
        assert by_node.get(cdf, 1) <= by_node.get(complexity, 0)

    def test_selected_action_targets_gap(self, world):
        orch = world["orchestrator"]
        result = orch.process(_interaction(world, "I wrote a correct linear-scan implementation.", 1))
        c = world["c"]
        # The engine should NOT re-teach the strong skills.
        strong_ids = {
            c.knowledge_repository.get_node_by_slug(s).id
            for s in ("normalize_weights", "construct_cdf")
        }
        assert result.selected_action is not None
        assert result.selected_action.target_node_id not in strong_ids

    def test_misconception_suspected_from_diagnostic_evidence(self, world):
        orch = world["orchestrator"]
        orch.process(_interaction(world, "I get the cumulative boundary wrong at the first bucket.", 4))
        c = world["c"]
        active = c.misconception_service.list_active_misconceptions(world["learner"].id)
        assert active, "diagnostic evidence should raise a misconception"
        mc_node = c.knowledge_repository.get_node_by_slug("cdf_is_normalized_weights")
        assert any(m.misconception_node_id == mc_node.id for m in active)

    def test_result_shape(self, world):
        orch = world["orchestrator"]
        r = orch.process(_interaction(world, "I normalize the weights and build the CDF.", 1))
        assert r.new_evidence, "evidence was persisted"
        assert r.updated_states
        assert r.current_topic_slug == "weighted_sampling_from_scratch"
        assert r.frontier  # frontier expanded
        assert r.selected_action is not None

    def test_each_evidence_traceable_to_update(self, world):
        orch = world["orchestrator"]
        r1 = orch.process(_interaction(world, "I normalize the weights and build the CDF.", 1))
        c = world["c"]
        updates = c.state_update_repository.list_updates(learner_id=world["learner"].id)
        # Every persisted evidence that produced an update has an audit row.
        assert len(updates) == len(r1.updated_states)
        assert all(u.evidence_id in {e.id for e in r1.new_evidence} for u in updates)