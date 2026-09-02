"""Ensure the project root is importable when running tests from anywhere,
and share fixtures/helpers for both the parent app and the learning_partner
(in-repo) tests.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.learning_partner.domain.knowledge import KnowledgeNode
from core.learning_partner.domain.types import NodeType
from core.learning_partner.storage.assessment_repositories import (
    SQLAssessmentTargetRepository,
    SQLAssessmentTaskRepository,
)
from core.learning_partner.storage.database import Base
from core.learning_partner.storage.evidence_repositories import SQLEvidenceRepository
from core.learning_partner.storage.learner_repositories import SQLLearnerModelRepository
from core.learning_partner.storage.repositories import SQLKnowledgeGraphRepository
from core.learning_partner.storage import models  # noqa: F401  (register tables)
from core.learning_partner.storage.update_repositories import (
    SQLFrontierRepository,
    SQLLearnerMisconceptionRepository,
    SQLStateUpdateRepository,
)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        yield s


@pytest.fixture()
def repository(session):
    """In-memory SQLite knowledge-graph repository, fresh per test."""
    return SQLKnowledgeGraphRepository(session)


@pytest.fixture()
def learner_repository(session):
    """In-memory SQLite learner-model repository, fresh per test."""
    return SQLLearnerModelRepository(session)


@pytest.fixture()
def evidence_repository(session):
    """In-memory SQLite evidence repository, fresh per test."""
    return SQLEvidenceRepository(session)


@pytest.fixture()
def task_repository(session):
    """In-memory SQLite assessment-task repository, fresh per test."""
    return SQLAssessmentTaskRepository(session)


@pytest.fixture()
def target_repository(session):
    """In-memory SQLite assessment-target repository, fresh per test."""
    return SQLAssessmentTargetRepository(session)


@pytest.fixture()
def update_repo(session):
    """In-memory SQLite state-update audit repository, fresh per test."""
    return SQLStateUpdateRepository(session)


@pytest.fixture()
def misconception_repo(session):
    """In-memory SQLite misconception repository, fresh per test."""
    return SQLLearnerMisconceptionRepository(session)


@pytest.fixture()
def frontier_repo(session):
    """In-memory SQLite frontier repository, fresh per test."""
    return SQLFrontierRepository(session)


@pytest.fixture()
def misconception_service(misconception_repo, learner_repository, repository, evidence_repository):
    from core.learning_partner.services.misconception import MisconceptionService

    return MisconceptionService(
        misconception_repo, learner_repository, repository, evidence_repository
    )


@pytest.fixture()
def frontier_service(frontier_repo, learner_repository, repository, task_repository, target_repository):
    from core.learning_partner.services.frontier import FrontierService

    return FrontierService(
        frontier_repo, learner_repository, repository, task_repository, target_repository
    )


@pytest.fixture()
def policy_engine(learner_repository, repository, misconception_repo, task_repository, target_repository):
    from core.learning_partner.services.policy import PolicyEngine

    return PolicyEngine(
        learner_repository, repository, misconception_repo, task_repository, target_repository
    )


@pytest.fixture()
def service(repository):
    from core.learning_partner.services.knowledge_graph import KnowledgeGraphService

    return KnowledgeGraphService(repository)


@pytest.fixture()
def learner_service(learner_repository, repository):
    from core.learning_partner.services.learner_model import LearnerModelService

    return LearnerModelService(learner_repository, repository)


@pytest.fixture()
def evidence_service(evidence_repository, learner_repository, repository):
    from core.learning_partner.services.evidence import EvidenceService

    return EvidenceService(evidence_repository, learner_repository, repository)


@pytest.fixture()
def assessment_service(task_repository, target_repository, repository):
    from core.learning_partner.services.assessment import AssessmentService

    return AssessmentService(task_repository, target_repository, repository)


@pytest.fixture()
def seeded_repository(repository):
    """Knowledge graph seeded with the Weighted Sampling From Scratch graph."""
    from core.learning_partner.seed import seed_weighted_sampling

    seed_weighted_sampling(repository)
    return repository


@pytest.fixture()
def sample_node() -> KnowledgeNode:
    return KnowledgeNode(
        type=NodeType.CONCEPT,
        slug="probability",
        name="Probability",
        description="Measure of likelihood.",
    )


def make_node(
    slug: str,
    ntype: NodeType = NodeType.CONCEPT,
    name: str | None = None,
) -> KnowledgeNode:
    return KnowledgeNode(type=ntype, slug=slug, name=name or slug.replace("_", " ").title())


def make_edge(
    source: KnowledgeNode,
    target: KnowledgeNode,
    edge_type,
    **kwargs,
):
    from core.learning_partner.domain.knowledge import KnowledgeEdge

    return KnowledgeEdge(source_node_id=source.id, target_node_id=target.id, edge_type=edge_type, **kwargs)
