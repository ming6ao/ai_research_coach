"""Application container: wires repositories and services for a session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from .storage.assessment_repositories import (
    SQLAssessmentTargetRepository,
    SQLAssessmentTaskRepository,
)
from .storage.evidence_repositories import SQLEvidenceRepository
from .storage.learner_repositories import SQLLearnerModelRepository
from .storage.repositories import SQLKnowledgeGraphRepository
from .storage.update_repositories import (
    SQLFrontierRepository,
    SQLLearnerMisconceptionRepository,
    SQLStateUpdateRepository,
)


@dataclass
class Container:
    session: Session
    knowledge_repository: SQLKnowledgeGraphRepository
    learner_repository: SQLLearnerModelRepository
    evidence_repository: SQLEvidenceRepository
    task_repository: SQLAssessmentTaskRepository
    target_repository: SQLAssessmentTargetRepository
    state_update_repository: SQLStateUpdateRepository
    misconception_repository: SQLLearnerMisconceptionRepository
    frontier_repository: SQLFrontierRepository

    knowledge_service: KnowledgeGraphService
    learner_service: LearnerModelService
    evidence_service: EvidenceService
    assessment_service: AssessmentService
    update_service: LearnerUpdateService
    misconception_service: MisconceptionService
    frontier_service: FrontierService
    policy_engine: PolicyEngine


def build_container(session: Session, *, configs: Optional[dict] = None) -> Container:
    """Construct the full application wiring on top of ``session``.

    ``configs`` may carry optional ``update``, ``misconception``,
    ``frontier``, and ``policy`` config objects keyed by name.
    """
    # Imported lazily to avoid a circular import through the services package.
    from .services.assessment import AssessmentService
    from .services.evidence import EvidenceService
    from .services.frontier import FrontierService
    from .services.knowledge_graph import KnowledgeGraphService
    from .services.learner_model import LearnerModelService
    from .services.misconception import MisconceptionService
    from .services.policy import PolicyEngine
    from .services.update import LearnerUpdateService
    from .domain.update import DEFAULT_UPDATE_CONFIG
    from .domain.misconception import DEFAULT_MISCONCEPTION_CONFIG
    from .domain.frontier import DEFAULT_FRONTIER_CONFIG
    from .domain.action import DEFAULT_POLICY_CONFIG

    configs = configs or {}
    knowledge_repo = SQLKnowledgeGraphRepository(session)
    learner_repo = SQLLearnerModelRepository(session)
    evidence_repo = SQLEvidenceRepository(session)
    task_repo = SQLAssessmentTaskRepository(session)
    target_repo = SQLAssessmentTargetRepository(session)
    update_repo = SQLStateUpdateRepository(session)
    misconception_repo = SQLLearnerMisconceptionRepository(session)
    frontier_repo = SQLFrontierRepository(session)

    knowledge_service = KnowledgeGraphService(knowledge_repo)
    learner_service = LearnerModelService(learner_repo, knowledge_repo)
    evidence_service = EvidenceService(evidence_repo, learner_repo, knowledge_repo)
    assessment_service = AssessmentService(task_repo, target_repo, knowledge_repo)
    update_service = LearnerUpdateService(
        learner_repo, knowledge_repo, update_repo,
        config=configs.get("update", DEFAULT_UPDATE_CONFIG),
    )
    misconception_service = MisconceptionService(
        misconception_repo, learner_repo, knowledge_repo, evidence_repo,
        config=configs.get("misconception", DEFAULT_MISCONCEPTION_CONFIG),
    )
    frontier_service = FrontierService(
        frontier_repo, learner_repo, knowledge_repo, task_repo, target_repo,
        config=configs.get("frontier", DEFAULT_FRONTIER_CONFIG),
    )
    policy_engine = PolicyEngine(
        learner_repo, knowledge_repo, misconception_repo, task_repo, target_repo,
        config=configs.get("policy", DEFAULT_POLICY_CONFIG),
    )

    return Container(
        session=session,
        knowledge_repository=knowledge_repo,
        learner_repository=learner_repo,
        evidence_repository=evidence_repo,
        task_repository=task_repo,
        target_repository=target_repo,
        state_update_repository=update_repo,
        misconception_repository=misconception_repo,
        frontier_repository=frontier_repo,
        knowledge_service=knowledge_service,
        learner_service=learner_service,
        evidence_service=evidence_service,
        assessment_service=assessment_service,
        update_service=update_service,
        misconception_service=misconception_service,
        frontier_service=frontier_service,
        policy_engine=policy_engine,
    )