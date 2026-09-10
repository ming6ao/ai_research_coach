"""Services layer: application logic that composes repositories.

Traversal is implemented here (BFS over edges loaded from the repository) rather
than as recursive SQL, keeping the database portable and domain logic in Python.
"""

from .knowledge_graph import KnowledgeGraphService
from .learner_model import LearnerModelService
from .evidence import EvidenceService
from .assessment import AssessmentService
from .update import LearnerUpdateService
from .misconception import MisconceptionService
from .frontier import FrontierService
from .policy import PolicyEngine
from .orchestrator import LearningOrchestrator
from .assessors import (
    EvidenceAssessor,
    RuleBasedEvidenceAssessor,
    ScriptedEvidenceAssessor,
)
from . import traversal

__all__ = [
    "KnowledgeGraphService",
    "LearnerModelService",
    "EvidenceService",
    "AssessmentService",
    "LearnerUpdateService",
    "MisconceptionService",
    "FrontierService",
    "PolicyEngine",
    "LearningOrchestrator",
    "EvidenceAssessor",
    "RuleBasedEvidenceAssessor",
    "ScriptedEvidenceAssessor",
    "traversal",
]