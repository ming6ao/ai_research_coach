from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EvaluationResult:
    task_id: str
    skill: str
    score: float
    max_score: float
    rationale: str
    coach: Optional[dict] = None

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
            "coach": self.coach,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            d["task_id"],
            d["skill"],
            d["score"],
            d["max_score"],
            d["rationale"],
            d.get("coach"),
        )


@dataclass
class CoachStep:
    """One step on the path to the correct solution."""

    title: str
    explanation: str
    code: Optional[str] = None

    def to_dict(self):
        return {"title": self.title, "explanation": self.explanation, "code": self.code}

    @classmethod
    def from_dict(cls, d):
        return cls(
            d.get("title", ""),
            d.get("explanation", ""),
            d.get("code"),
        )


@dataclass
class CoachContent:
    """Structured teaching response shown after a submit.

    Identifies the user's misconception/gap and walks them step-by-step to the
    correct solution. `feedback` remains the concise summary used in reports.
    """

    feedback: str = ""
    misconception: str = ""
    steps: list = field(default_factory=list)

    def to_dict(self):
        return {
            "feedback": self.feedback,
            "misconception": self.misconception,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            d.get("feedback", ""),
            d.get("misconception", ""),
            [CoachStep.from_dict(s) for s in d.get("steps", [])],
        )