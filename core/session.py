from dataclasses import dataclass, field
from typing import List

from core.config import load_yaml
from evaluators.base import EvaluationResult


@dataclass
class Session:
    candidate: str
    role: str
    tasks: List[dict] = field(default_factory=list)
    index: int = 0
    results: List[EvaluationResult] = field(default_factory=list)

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

    def to_dict(self):
        return {
            "candidate": self.candidate,
            "role": self.role,
            "tasks": self.tasks,
            "index": self.index,
            "results": [r.to_dict() for r in self.results],
        }

    @classmethod
    def from_dict(cls, d):
        s = cls(candidate=d["candidate"], role=d["role"], tasks=d["tasks"], index=d["index"])
        s.results = [EvaluationResult.from_dict(r) for r in d["results"]]
        return s
