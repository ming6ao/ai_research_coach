from dataclasses import dataclass, field
from typing import Dict, List, Set

from core.config import load_yaml
from core.score import INITIAL_SCORE, INITIAL_CONFIDENCE
from evaluators.base import EvaluationResult


@dataclass
class SkillState:
    """Tracks score and confidence for a single skill."""
    score: float = INITIAL_SCORE
    confidence: float = INITIAL_CONFIDENCE
    questions_answered: int = 0
    evidence: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "score": self.score,
            "confidence": self.confidence,
            "questions_answered": self.questions_answered,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            score=d.get("score", INITIAL_SCORE),
            confidence=d.get("confidence", INITIAL_CONFIDENCE),
            questions_answered=d.get("questions_answered", 0),
            evidence=d.get("evidence", []),
        )


@dataclass
class Session:
    candidate: str
    role: str
    tasks: List[dict] = field(default_factory=list)
    index: int = 0
    results: List[EvaluationResult] = field(default_factory=list)
    skill_states: Dict[str, SkillState] = field(default_factory=dict)
    asked_task_ids: Set[str] = field(default_factory=set)

    def __post_init__(self):
        if not self.tasks:
            roles = load_yaml("roles.yaml")["roles"]
            if self.role not in roles:
                raise ValueError(f"Unknown role: {self.role}")
            self.role_cfg = roles[self.role]
            all_tasks = load_yaml("tasks.yaml")["tasks"]
            self.tasks = [t for t in all_tasks if t.get("role") == self.role]
        else:
            roles = load_yaml("roles.yaml")["roles"]
            self.role_cfg = roles[self.role]

        # Initialize skill states for all skills in the role
        for skill in self.role_cfg["skills"]:
            if skill["id"] not in self.skill_states:
                self.skill_states[skill["id"]] = SkillState()

    def get_skill_state(self, skill_id: str) -> SkillState:
        """Get the current state for a skill, initializing if needed."""
        if skill_id not in self.skill_states:
            self.skill_states[skill_id] = SkillState()
        return self.skill_states[skill_id]

    def to_dict(self):
        return {
            "candidate": self.candidate,
            "role": self.role,
            "tasks": self.tasks,
            "index": self.index,
            "results": [r.to_dict() for r in self.results],
            "skill_states": {k: v.to_dict() for k, v in self.skill_states.items()},
            "asked_task_ids": list(self.asked_task_ids),
        }

    @classmethod
    def from_dict(cls, d):
        s = cls(candidate=d["candidate"], role=d["role"], tasks=d["tasks"], index=d["index"])
        s.results = [EvaluationResult.from_dict(r) for r in d["results"]]
        s.skill_states = {
            k: SkillState.from_dict(v) for k, v in d.get("skill_states", {}).items()
        }
        s.asked_task_ids = set(d.get("asked_task_ids", []))
        return s
