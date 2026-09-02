"""Enums for the knowledge graph domain."""

from enum import Enum


class NodeType(str, Enum):
    """What a knowledge node represents."""

    CONCEPT = "concept"
    SKILL = "skill"
    PROCEDURE = "procedure"
    PROBLEM = "problem"
    STRATEGY = "strategy"
    MISCONCEPTION = "misconception"
    DOMAIN = "domain"


class EdgeType(str, Enum):
    """Semantics of a directed relationship between two knowledge nodes."""

    PREREQUISITE_OF = "prerequisite_of"
    REQUIRES = "requires"
    PART_OF = "part_of"
    COMPOSED_OF = "composed_of"
    APPLIED_IN = "applied_in"
    CONTRASTS_WITH = "contrasts_with"
    COMMONLY_CONFUSED_WITH = "commonly_confused_with"
    GENERALIZES_TO = "generalizes_to"
    SPECIALIZES_TO = "specializes_to"
    ENABLES = "enables"
    ALTERNATIVE_TO = "alternative_to"


class NodeStatus(str, Enum):
    """Lifecycle state of a knowledge node."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"