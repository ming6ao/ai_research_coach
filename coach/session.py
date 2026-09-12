import re
from dataclasses import dataclass, field
from typing import Dict, List, Set

from coach.hints import select_hints
from coach.score import INITIAL_SCORE, INITIAL_VARIANCE, confidence_from_variance
from coach.judge import EvaluationResult


def _load_bank_tasks(candidate: str) -> list:
    """Load the visible task bank from the DB.

    The YAML bank was removed; tasks are user-created or seeded rows in
    the ``tasks`` table. An empty bank is valid (the UI prompts the user
    to enter their own question).
    """
    try:
        from coach.tasks import list_visible_tasks

        return list_visible_tasks(candidate or "system")
    except Exception:
        return []


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
    """A candidate's coaching session against the unified skill tree.

    All candidates are coached the same way: every task in the bank is
    eligible and the same skill tree is measured for everyone. ``candidate``
    is the user email or a ``guest-<hex>`` id; it drives learner identity,
    resume ownership, and history scoping only (no behavioral difference
    between the two).
    """
    candidate: str
    tasks: List[dict] = field(default_factory=list)
    index: int = 0
    results: List[EvaluationResult] = field(default_factory=list)
    skill_states: Dict[str, SkillState] = field(default_factory=dict)
    asked_task_ids: Set[str] = field(default_factory=set)
    viewed_hints: Dict[str, List[str]] = field(default_factory=dict)
    generated_task_ids: Set[str] = field(default_factory=set)

    def __post_init__(self):
        if not self.tasks:
            self.tasks = _load_bank_tasks(self.candidate)

    def get_skill_state(self, skill_id: str) -> SkillState:
        """Get the current state for a skill, initializing if needed."""
        if skill_id not in self.skill_states:
            restored = None
            try:
                from coach.tasks import get_skill_belief

                restored = get_skill_belief(self.candidate, skill_id)
            except Exception:
                restored = None
            if restored:
                self.skill_states[skill_id] = SkillState(
                    score=restored.get("mean", INITIAL_SCORE),
                    variance=restored.get("variance", INITIAL_VARIANCE),
                    questions_answered=restored.get("questions_answered", 0),
                )
            else:
                self.skill_states[skill_id] = SkillState()
        return self.skill_states[skill_id]

    def add_generated_task(self, task: dict) -> None:
        """Persist a generated remediation task in the session and track it."""
        self.tasks.append(task)
        self.generated_task_ids.add(task["id"])

    def to_dict(self):
        return {
            "candidate": self.candidate,
            "tasks": self.tasks,
            "index": self.index,
            "results": [r.to_dict() for r in self.results],
            "skill_states": {k: v.to_dict() for k, v in self.skill_states.items()},
            "asked_task_ids": list(self.asked_task_ids),
            "viewed_hints": self.viewed_hints,
            "generated_task_ids": list(self.generated_task_ids),
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
        s.generated_task_ids = set(d.get("generated_task_ids", []))
        return s


def build_code_stub(task: dict) -> str | None:
    """Build an editor scaffold for a code task.

    Scaffold-mode tasks already carry a `scaffold`. For function-mode tasks
    (no scaffold) we generate a stub from the signature mentioned in the prompt
    so the coding area is pre-filled instead of blank.
    """
    if task.get("scaffold"):
        return task["scaffold"]
    m = re.search(r"def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", task.get("prompt", ""))
    if m:
        name, params = m.group(1), m.group(2)
        return f"def {name}({params}):\n    # TODO: implement {name}\n    pass\n"
    return None


def task_view(task: dict, session: Session) -> dict | None:
    """Build the client-facing view of a task (hints pre-revealed by ability)."""
    if task is None:
        return None
    ability = session.get_skill_state(task["skill"]).score
    view = {
        "id": task["id"],
        "skill": task["skill"],
        "type": "code",
        "prompt": task["prompt"],
        "difficulty": task.get("difficulty", 1),
        "scaffold": build_code_stub(task),
        "hints": select_hints(task, ability),
    }
    if task.get("context_notes"):
        view["context_notes"] = task["context_notes"]
    if task.get("generated"):
        view["remediation"] = {"focus": task.get("target_text")}
    return view