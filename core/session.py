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
    """A candidate's assessment session against the unified skill tree.

    All candidates are evaluated the same way: every task in the bank is
    eligible and the same skill tree is measured for everyone.

    `mode` is either "assessment" (scored, with feedback) or "practice"
    (anonymous browsing — no submission, no scoring, no feedback).
    """
    candidate: str
    tasks: List[dict] = field(default_factory=list)
    index: int = 0
    results: List[EvaluationResult] = field(default_factory=list)
    skill_states: Dict[str, SkillState] = field(default_factory=dict)
    asked_task_ids: Set[str] = field(default_factory=set)
    viewed_hints: Dict[str, List[str]] = field(default_factory=dict)
    mode: str = "assessment"

    def __post_init__(self):
        cfg = load_yaml("skills.yaml")
        self.skills_cfg = cfg.get("skills", [])
        self.max_time_min = float(cfg.get("max_time_min", 45.0))
        if not self.tasks:
            all_tasks = load_yaml("tasks.yaml")["tasks"]
            self.tasks = list(all_tasks)

        # Initialize skill states for all skills in the tree
        for skill in self.skills_cfg:
            if skill["id"] not in self.skill_states:
                self.skill_states[skill["id"]] = SkillState()

    def get_skill_state(self, skill_id: str) -> SkillState:
        """Get the current state for a skill, initializing if needed."""
        if skill_id not in self.skill_states:
            self.skill_states[skill_id] = SkillState()
        return self.skill_states[skill_id]

    def get_skill_cfg(self, skill_id: str) -> dict:
        """Get the config block for a skill, or an importance-3 default."""
        for skill in self.skills_cfg:
            if skill["id"] == skill_id:
                return skill
        return {"id": skill_id, "name": skill_id, "importance": 3}

    def to_dict(self):
        return {
            "candidate": self.candidate,
            "tasks": self.tasks,
            "index": self.index,
            "results": [r.to_dict() for r in self.results],
            "skill_states": {k: v.to_dict() for k, v in self.skill_states.items()},
            "asked_task_ids": list(self.asked_task_ids),
            "viewed_hints": self.viewed_hints,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, d):
        s = cls(candidate=d["candidate"], tasks=d["tasks"], index=d["index"])
        s.results = [EvaluationResult.from_dict(r) for r in d["results"]]
        s.skill_states = {
            k: SkillState.from_dict(v) for k, v in d.get("skill_states", {}).items()
        }
        s.asked_task_ids = set(d.get("asked_task_ids", []))
        s.viewed_hints = dict(d.get("viewed_hints", {}))
        s.mode = d.get("mode", "assessment")
        return s