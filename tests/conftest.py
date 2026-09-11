"""Ensure the project root is importable when running tests from anywhere,
and share fixtures/helpers for both the coach app and the learner
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

from learner.graph import KnowledgeNode
from learner.types import NodeType
from coach.db import Base
from learner.evidence import SQLEvidenceRepository
from learner.states import SQLLearnerModelRepository
from learner.graph import SQLKnowledgeGraphRepository
from learner import evidence, frontier, graph, misconception, states  # noqa: F401  (register tables)
from learner.frontier import SQLFrontierRepository
from learner.misconception import SQLLearnerMisconceptionRepository


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
def misconception_repo(session):
    """In-memory SQLite misconception repository, fresh per test."""
    return SQLLearnerMisconceptionRepository(session)


@pytest.fixture()
def frontier_repo(session):
    """In-memory SQLite frontier repository, fresh per test."""
    return SQLFrontierRepository(session)


@pytest.fixture()
def misconception_service(misconception_repo, learner_repository, repository, evidence_repository):
    from learner.misconception import MisconceptionService

    return MisconceptionService(
        misconception_repo, learner_repository, repository, evidence_repository
    )


@pytest.fixture()
def frontier_service(frontier_repo, learner_repository, repository):
    from learner.frontier import FrontierService

    return FrontierService(
        frontier_repo, learner_repository, repository
    )


@pytest.fixture()
def policy_engine(learner_repository, repository, misconception_repo):
    from learner.policy import PolicyEngine

    return PolicyEngine(
        learner_repository, repository, misconception_repo
    )


@pytest.fixture()
def service(repository):
    from learner.graph import KnowledgeGraphService

    return KnowledgeGraphService(repository)


@pytest.fixture()
def learner_service(learner_repository, repository):
    from learner.states import LearnerModelService

    return LearnerModelService(learner_repository, repository)


@pytest.fixture()
def evidence_service(evidence_repository, learner_repository, repository):
    from learner.evidence import EvidenceService

    return EvidenceService(evidence_repository, learner_repository, repository)


@pytest.fixture()
def seeded_repository(repository):
    """Knowledge graph seeded with the Weighted Sampling From Scratch graph."""
    from tests.learner.fixtures import seed_weighted_sampling

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
    from learner.graph import KnowledgeEdge

    return KnowledgeEdge(source_node_id=source.id, target_node_id=target.id, edge_type=edge_type, **kwargs)
