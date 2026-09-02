"""Domain layer.

Pure domain logic and interfaces. No SQLAlchemy, no I/O.
"""

from .knowledge import KnowledgeNode, KnowledgeEdge
from .types import NodeType, EdgeType, NodeStatus
from .learner import (
    Learner,
    LearnerKnowledgeState,
    StateStatus,
    UNKNOWN_MASTERY,
    UNKNOWN_UNCERTAINTY,
    UNKNOWN_DIMENSION,
    UNCERTAINTY_THRESHOLD,
    LOW_MASTERY_THRESHOLD,
)
from .evidence import (
    Evidence,
    EvidenceFilter,
    EvidenceSummary,
    EvidenceType,
    ObservationStatus,
)
from .assessment import (
    AssessmentTask,
    AssessmentTarget,
    TaskType,
    TargetRole,
)
from .update import (
    UpdateConfig,
    DEFAULT_UPDATE_CONFIG,
    UpdateEngine,
    LearnerUpdate,
    StateUpdateRecord,
)
from .misconception import (
    LearnerMisconception,
    MisconceptionEvidenceLink,
    MisconceptionStatus,
    EvidenceRelationship,
    MisconceptionConfig,
)
from .frontier import (
    LearnerFrontier,
    FrontierStatus,
    FrontierConfig,
)
from .action import (
    CandidateAction,
    ActionType,
    PolicyConfig,
)
from .orchestrator import (
    LearnerInteraction,
    OrchestratorResult,
)
from .errors import (
    KnowledgeGraphError,
    DuplicateSlugError,
    NodeNotFoundError,
    DuplicateEdgeError,
    SelfEdgeError,
    NodeReferencedError,
    LearnerNotFoundError,
    StateNotFoundError,
    EvidenceNotFoundError,
    DuplicateEvidenceError,
    TaskNotFoundError,
    DuplicateTargetError,
    MisconceptionNotFoundError,
    NotMisconceptionNodeError,
)

__all__ = [
    "KnowledgeNode",
    "KnowledgeEdge",
    "NodeType",
    "EdgeType",
    "NodeStatus",
    "Learner",
    "LearnerKnowledgeState",
    "StateStatus",
    "UNKNOWN_MASTERY",
    "UNKNOWN_UNCERTAINTY",
    "UNKNOWN_DIMENSION",
    "UNCERTAINTY_THRESHOLD",
    "LOW_MASTERY_THRESHOLD",
    "Evidence",
    "EvidenceFilter",
    "EvidenceSummary",
    "EvidenceType",
    "ObservationStatus",
    "AssessmentTask",
    "AssessmentTarget",
    "TaskType",
    "TargetRole",
    "UpdateConfig",
    "DEFAULT_UPDATE_CONFIG",
    "UpdateEngine",
    "LearnerUpdate",
    "StateUpdateRecord",
    "LearnerMisconception",
    "MisconceptionEvidenceLink",
    "MisconceptionStatus",
    "EvidenceRelationship",
    "MisconceptionConfig",
    "LearnerFrontier",
    "FrontierStatus",
    "FrontierConfig",
    "CandidateAction",
    "ActionType",
    "PolicyConfig",
    "LearnerInteraction",
    "OrchestratorResult",
    "KnowledgeGraphError",
    "DuplicateSlugError",
    "NodeNotFoundError",
    "DuplicateEdgeError",
    "SelfEdgeError",
    "NodeReferencedError",
    "LearnerNotFoundError",
    "StateNotFoundError",
    "EvidenceNotFoundError",
    "DuplicateEvidenceError",
    "TaskNotFoundError",
    "DuplicateTargetError",
    "MisconceptionNotFoundError",
    "NotMisconceptionNodeError",
]