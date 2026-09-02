"""CLI entry point: ``python -m core.learning_partner``.

Subcommands:
  seed   Create tables if needed and seed sample data.
  demo   Seed, then print a traversal demo for the Weighted Sampling graph.
"""

from __future__ import annotations

import sys


def _service():
    from core.learning_partner.services.knowledge_graph import KnowledgeGraphService
    from core.learning_partner.storage.database import Base, create_session_factory
    from core.learning_partner.storage.repositories import SQLKnowledgeGraphRepository

    session_factory, engine = create_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    return KnowledgeGraphService(SQLKnowledgeGraphRepository(session)), session


def cmd_seed() -> int:
    from core.learning_partner.seed import seed_weighted_sampling

    service, session = _service()
    try:
        result = seed_weighted_sampling(service.repository)
        print(f"Seeded knowledge graph: {result}")
    finally:
        session.close()
    return 0


def cmd_demo() -> int:
    from core.learning_partner.seed import seed_weighted_sampling

    service, session = _service()
    try:
        seed_weighted_sampling(service.repository)

        problem = service.get_node_by_slug("weighted_sampling_from_scratch")
        print(f"\n=== {problem.name} ===")
        print("direct prerequisites:",
              ", ".join(n.slug for n in service.direct_prerequisites(problem.id)))
        print("ancestors (depth <= 2):",
              ", ".join(n.slug for n in service.ancestors(problem.id, max_depth=2)))

        prefix_sum = service.get_node_by_slug("prefix_sum")
        print(f"\n=== {prefix_sum.name} ===")
        print("descendants (depth <= 2):",
              ", ".join(n.slug for n in service.descendants(prefix_sum.id, max_depth=2)))
        print("neighbors:",
              ", ".join(n.slug for n in service.neighbors(prefix_sum.id)))
    finally:
        session.close()
    return 0


def cmd_learner() -> int:
    from core.learning_partner.domain.learner import LearnerKnowledgeState, StateStatus
    from core.learning_partner.seed import seed_weighted_sampling
    from core.learning_partner.services.learner_model import LearnerModelService
    from core.learning_partner.storage.database import Base, create_session_factory
    from core.learning_partner.storage.learner_repositories import SQLLearnerModelRepository
    from core.learning_partner.storage.repositories import SQLKnowledgeGraphRepository

    session_factory, engine = create_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        kg = SQLKnowledgeGraphRepository(session)
        seed_weighted_sampling(kg)
        learner_model = LearnerModelService(SQLLearnerModelRepository(session), kg)

        learner = learner_model.create_learner()
        problem = kg.get_node_by_slug("weighted_sampling_from_scratch")
        cdf = kg.get_node_by_slug("construct_cdf")

        unknown = learner_model.initialize_state(learner.id, problem.id)
        print(f"\n=== Unknown state for '{problem.name}' ===")
        print(f"mastery={unknown.mastery} uncertainty={unknown.uncertainty} "
              f"evidence={unknown.evidence_count} status={unknown.status.value} "
              f"is_low_mastery={unknown.is_low_mastery()}")

        assessed = learner_model.upsert_state(
            LearnerKnowledgeState(
                learner_id=learner.id,
                node_id=cdf.id,
                mastery=0.3,
                uncertainty=0.2,
                evidence_count=3,
                status=StateStatus.DEVELOPING,
            )
        )
        print(f"\n=== Assessed state for '{cdf.name}' ===")
        print(f"mastery={assessed.mastery} status={assessed.status.value} "
              f"is_low_mastery={assessed.is_low_mastery()}")
        print(f"\nlow mastery nodes: "
              f"{[kg.get_node(s.node_id).slug for s in learner_model.list_low_mastery_nodes(learner.id)]}")
        print(f"uncertain nodes:   "
              f"{[kg.get_node(s.node_id).slug for s in learner_model.list_uncertain_nodes(learner.id)]}")
    finally:
        session.close()
    return 0


def cmd_evidence() -> int:
    import uuid

    from core.learning_partner.domain.evidence import Evidence, EvidenceType, ObservationStatus
    from core.learning_partner.domain.learner import Learner
    from core.learning_partner.seed import seed_weighted_sampling
    from core.learning_partner.services.evidence import EvidenceService
    from core.learning_partner.storage.database import Base, create_session_factory
    from core.learning_partner.storage.evidence_repositories import SQLEvidenceRepository
    from core.learning_partner.storage.learner_repositories import SQLLearnerModelRepository
    from core.learning_partner.storage.repositories import SQLKnowledgeGraphRepository

    session_factory, engine = create_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        kg = SQLKnowledgeGraphRepository(session)
        seed_weighted_sampling(kg)
        learner = SQLLearnerModelRepository(session).create_learner(Learner())
        service = EvidenceService(
            SQLEvidenceRepository(session), SQLLearnerModelRepository(session), kg
        )

        problem = kg.get_node_by_slug("weighted_sampling_from_scratch")

        # A representative evidence record for the weighted-sampling problem.
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
            assessment_payload={"language": "python", "time_seconds": 612},
        )
        stored = service.add_evidence(record)
        summary = service.summarize(learner.id, problem.id)

        print(f"\n=== Evidence for '{problem.name}' ===")
        print(f"record id:       {stored.id}")
        print(f"type/status:     {stored.evidence_type.value} / {stored.observation_status.value}")
        print(f"correctness:     {stored.correctness}")
        print(f"observed_behavior: {stored.observed_behavior}")
        print(f"assessor_explanation: {stored.assessor_explanation}")
        print(f"\nsummary: observation_count={summary.observation_count} "
              f"partial={summary.partial_count} incorrect={summary.incorrect_count} "
              f"not_observed={summary.not_observed_count} "
              f"avg_correctness={summary.average_correctness}")
    finally:
        session.close()
    return 0


def cmd_assessment() -> int:
    import uuid

    from core.learning_partner.domain.assessment import TargetRole
    from core.learning_partner.seed import seed_weighted_sampling_task
    from core.learning_partner.services.assessment import AssessmentService
    from core.learning_partner.storage.assessment_repositories import (
        SQLAssessmentTargetRepository,
        SQLAssessmentTaskRepository,
    )
    from core.learning_partner.storage.database import Base, create_session_factory
    from core.learning_partner.storage.repositories import SQLKnowledgeGraphRepository

    session_factory, engine = create_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        kg = SQLKnowledgeGraphRepository(session)
        service = AssessmentService(
            SQLAssessmentTaskRepository(session),
            SQLAssessmentTargetRepository(session),
            kg,
        )
        result = seed_weighted_sampling_task(
            service.task_repository, service.target_repository, kg
        )
        task = service.get_task(uuid.UUID(result["task_id"]))
        print(f"\n=== Assessment task: {task.title} ===")
        print(f"type={task.task_type.value} difficulty={task.difficulty}")
        targets = service.list_targets_for_task(task.id)
        print("\ntargets:")
        for t in targets:
            node = kg.get_node(t.node_id)
            print(f"  {node.slug:<28} {t.target_role.value:<10} signal={t.expected_signal_strength}")

        norm = kg.get_node_by_slug("normalize_weights")
        print(f"\ntasks targeting 'normalize_weights' (primary): "
              f"{[t.title for t in service.find_tasks_for_node(norm.id, role=TargetRole.PRIMARY)]}")
    finally:
        session.close()
    return 0


def cmd_eval() -> int:
    """Run the bundled evaluation scenarios (Stage 10)."""
    import json
    from pathlib import Path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.learning_partner.harness.replay import ReplayEngine
    from core.learning_partner.storage.database import Base

    scenarios_dir = Path(__file__).resolve().parent / "harness" / "scenarios"
    all_passed = True
    for path in sorted(scenarios_dir.glob("*.json")):
        with open(path) as fh:
            scenario = json.load(fh)
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as session:
            report = ReplayEngine(session).run(scenario)
        engine.dispose()
        status = "PASS" if report.passed else "FAIL"
        all_passed = all_passed and report.passed
        print(f"[{status}] {report.scenario}")
        if not report.passed:
            for f in report.failures:
                print(f"    - {f}")
    print(f"\nAll scenarios passed: {all_passed}")
    return 0 if all_passed else 1


def cmd_simulate() -> int:
    """Simulate the 4-interaction end-to-end weighted-sampling session (Stage 9)."""
    import uuid

    from core.learning_partner.container import build_container
    from core.learning_partner.domain.orchestrator import LearnerInteraction
    from core.learning_partner.seed import (
        seed_misconceptions,
        seed_weighted_sampling,
        seed_weighted_sampling_task,
    )
    from core.learning_partner.services.assessors import RuleBasedEvidenceAssessor
    from core.learning_partner.services.orchestrator import LearningOrchestrator
    from core.learning_partner.storage.database import Base, create_session_factory

    RULES = [
        {"keywords": ["normalize", "cdf"], "node_slug": "normalize_weights",
         "evidence_type": "explanation", "observation_status": "correct",
         "correctness": 1.0, "confidence": 1.0, "independence": 1.0, "reasoning_quality": 1.0},
        {"keywords": ["normalize", "cdf"], "node_slug": "construct_cdf",
         "evidence_type": "explanation", "observation_status": "correct",
         "correctness": 1.0, "confidence": 1.0, "independence": 1.0, "reasoning_quality": 1.0},
        {"keywords": ["linear"], "node_slug": "normalize_weights",
         "evidence_type": "code", "observation_status": "correct",
         "correctness": 1.0, "confidence": 1.0, "independence": 1.0},
        {"keywords": ["linear"], "node_slug": "construct_cdf",
         "evidence_type": "code", "observation_status": "correct",
         "correctness": 1.0, "confidence": 1.0, "independence": 1.0},
        {"keywords": ["linear"], "node_slug": "map_sample_to_interval",
         "evidence_type": "code", "observation_status": "correct",
         "correctness": 1.0, "confidence": 1.0, "independence": 1.0},
        {"keywords": ["optimize"], "node_slug": "analyze_sampling_complexity",
         "evidence_type": "prediction", "observation_status": "partially_correct",
         "correctness": 0.5, "confidence": 0.5, "reasoning_quality": 0.6},
        {"keywords": ["boundary"], "node_slug": "handle_boundaries",
         "evidence_type": "code", "observation_status": "incorrect",
         "correctness": 0.0, "confidence": 0.8, "independence": 0.8},
        {"keywords": ["boundary"], "node_slug": "cdf_is_normalized_weights",
         "evidence_type": "debugging", "observation_status": "incorrect",
         "assessment_payload": {"misconception_node_slug": "cdf_is_normalized_weights",
                                "relationship": "supporting"}},
    ]

    session_factory, engine = create_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        c = build_container(session)
        seed_weighted_sampling(c.knowledge_repository)
        seed_weighted_sampling_task(c.task_repository, c.target_repository, c.knowledge_repository)
        seed_misconceptions(c.knowledge_repository)
        learner = c.learner_service.create_learner()
        problem = c.knowledge_repository.get_node_by_slug("weighted_sampling_from_scratch")
        task = c.task_repository.list_tasks()[0]

        resolver = lambda slug: c.knowledge_repository.get_node_by_slug(slug).id if c.knowledge_repository.get_node_by_slug(slug) else None  # noqa: E731
        orch = LearningOrchestrator(c, RuleBasedEvidenceAssessor(RULES, resolver))

        messages = [
            "I normalize the weights and build the CDF.",
            "I wrote a correct linear-scan implementation.",
            "To optimize repeated sampling I'd binary search.",
            "I get the cumulative boundary wrong at the first bucket.",
        ]
        for i, msg in enumerate(messages):
            r = orch.process(LearnerInteraction(
                learner_id=learner.id,
                session_id=uuid.uuid4(),
                interaction_id=uuid.uuid4(),
                topic_node_id=problem.id,
                assessment_task_id=task.id,
                message=msg,
            ))
            print(f"\n=== Interaction {i+1}: {msg} ===")
            for ev in r.new_evidence:
                node = c.knowledge_repository.get_node(ev.node_id)
                print(f"  evidence: {node.slug} {ev.evidence_type.value} {ev.observation_status.value}")
            if r.selected_action:
                node = c.knowledge_repository.get_node(r.selected_action.target_node_id)
                print(f"  next: {r.selected_action.action_type.value} -> {node.slug}")

        print("\n=== Final learner states ===")
        for s in c.learner_service.list_learner_states(learner.id):
            node = c.knowledge_repository.get_node(s.node_id)
            print(f"  {node.slug:<28} mastery={s.mastery:.3f} unc={s.uncertainty:.3f} "
                  f"evidence={s.evidence_count} status={s.status.value}")
    finally:
        session.close()
    return 0


COMMANDS = {
    "seed": cmd_seed,
    "demo": cmd_demo,
    "learner": cmd_learner,
    "evidence": cmd_evidence,
    "assessment": cmd_assessment,
    "eval": cmd_eval,
    "simulate": cmd_simulate,
}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] in COMMANDS:
        return COMMANDS[argv[0]]()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())