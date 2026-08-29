from dataclasses import dataclass, field
from typing import Dict, List, Set

from core.config import load_yaml
from core.score import INITIAL_SCORE, INITIAL_VARIANCE, confidence_from_variance
from evaluators.base import EvaluationResult


@dataclass
class SkillState:
    """Gaussian belief over a single skill's mastery plus supporting metadata.

    `score` is the posterior mean (mu) of mastery on [0, 1]; `variance` is the
    posterior uncertainty used by the question picker. `confidence` is derived
    from the variance so the report/UI can keep using it as-is.
    """
    score: float = INITIAL_SCORE
    variance: float = INITIAL_VARIANCE
    questions_answered: int = 0
    evidence: List[str] = field(default_factory=list)
    hints_used: List[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        return confidence_from_variance(self.variance)

    def to_dict(self):
        return {
            "score": self.score,
            "variance": self.variance,
            "confidence": self.confidence,
            "questions_answered": self.questions_answered,
            "evidence": self.evidence,
            "hints_used": self.hints_used,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            score=d.get("score", INITIAL_SCORE),
            variance=d.get("variance", INITIAL_VARIANCE),
            questions_answered=d.get("questions_answered", 0),
            evidence=d.get("evidence", []),
            hints_used=d.get("hints_used", []),
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
    viewed_hints: Dict[str, List[str]] = field(default_factory=dict)

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
            "viewed_hints": self.viewed_hints,
        }

    @classmethod
    def from_dict(cls, d):
        s = cls(candidate=d["candidate"], role=d["role"], tasks=d["tasks"], index=d["index"])
        s.results = [EvaluationResult.from_dict(r) for r in d["results"]]
        s.skill_states = {
            k: SkillState.from_dict(v) for k, v in d.get("skill_states", {}).items()
        }
        s.asked_task_ids = set(d.get("asked_task_ids", []))
        s.viewed_hints = dict(d.get("viewed_hints", {}))
        return s