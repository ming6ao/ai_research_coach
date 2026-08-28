from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EvaluationResult:
    task_id: str
    skill: str
    score: float
    max_score: float
    rationale: str

    @property
    def fraction(self) -> float:
        return self.score / self.max_score if self.max_score else 0.0

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "skill": self.skill,
            "score": self.score,
            "max_score": self.max_score,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(d["task_id"], d["skill"], d["score"], d["max_score"], d["rationale"])


class Evaluator(ABC):
    @abstractmethod
    def evaluate(self, task: dict, answer: str) -> EvaluationResult:
        ...
