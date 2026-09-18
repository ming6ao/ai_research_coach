import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from coach.area_score import AreaState
from coach.score import INITIAL_SCORE, INITIAL_VARIANCE, confidence_from_variance
from coach.judge import EvaluationResult
from coach.taxonomy import area_of, domain_of


def _load_bank_tasks(candidate: str) -> list:
    """Load the visible task bank from the DB.

    Tasks live in the ``tasks`` table (the DB is the source of truth; there
    is no code-embedded bank). An empty bank is valid (the UI prompts the user
    to enter their own question). Generated tasks (adaptive drills/challenges)
    are excluded: they belong to the session that produced them and are never
    pickable bank questions.
    """
    try:
        from coach.tasks import list_visible_tasks

        return [
            t for t in list_visible_tasks(candidate or "system") if not t.get("generated")
        ]
    except Exception:
        return []


@dataclass
class SkillState:
    """Gaussian belief over the candidate's overall ability plus metadata.

    `score` is the posterior mean (mu) of mastery on [0, 1]; `variance` is the
    posterior uncertainty used by the question picker. `confidence` is derived
    from the variance so the report/UI can keep using it as-is.
    """
    score: float = INITIAL_SCORE
    variance: float = INITIAL_VARIANCE
    questions_answered: int = 0
    evidence: List[str] = field(default_factory=list)

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
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            score=d.get("score", INITIAL_SCORE),
            variance=d.get("variance", INITIAL_VARIANCE),
            questions_answered=d.get("questions_answered", 0),
            evidence=d.get("evidence", []),
        )


@dataclass
class Session:
    """A candidate's coaching session with a single overall ability belief.

    All candidates are coached the same way: every task in the bank is
    eligible and one overall ability is tracked for everyone. ``candidate``
    is the user email or a ``guest-<hex>`` id; it drives learner identity,
    resume ownership, and history scoping only (no behavioral difference
    between the two).
    """
    candidate: str
    tasks: List[dict] = field(default_factory=list)
    index: int = 0
    results: List[EvaluationResult] = field(default_factory=list)
    ability: SkillState = field(default_factory=SkillState)
    asked_task_ids: Set[str] = field(default_factory=set)
    generated_task_ids: Set[str] = field(default_factory=set)
    node_states: Dict[str, AreaState] = field(default_factory=dict)
    # Phased delivery bookkeeping: task_id -> phases passed / attempts on the
    # current phase. ``submission_index`` is the monotonic step counter (it
    # replaces ``index`` for ``session_steps.step_index`` so repeated phase
    # submissions never collide).
    task_progress: Dict[str, int] = field(default_factory=dict)
    phase_attempts: Dict[str, int] = field(default_factory=dict)
    submission_index: int = 0
    _area_restored: bool = field(default=False, init=False)

    def __post_init__(self):
        if not self.tasks:
            self.tasks = _load_bank_tasks(self.candidate)

    def get_skill_state(self, skill_id: str | None = None) -> SkillState:
        """Return the candidate's overall ability belief (legacy name kept).

        ``skill_id`` is accepted but ignored so old callers keep working.
        """
        restored = None
        if self.ability.questions_answered == 0 and not self.ability.evidence:
            try:
                from coach.tasks import get_skill_belief

                restored = get_skill_belief(self.candidate)
            except Exception:
                restored = None
            if restored:
                self.ability = SkillState(
                    score=restored.get("mean", INITIAL_SCORE),
                    variance=restored.get("variance", INITIAL_VARIANCE),
                    questions_answered=restored.get("questions_answered", 0),
                )
        return self.ability

    def get_ability(self) -> SkillState:
        """Return the candidate's overall ability belief."""
        return self.get_skill_state()

    def ensure_area_beliefs(self) -> None:
        """Load persisted per-node statistics into this session."""
        self._restore_node_beliefs()

    def add_generated_task(self, task: dict) -> None:
        """Persist a generated remediation task in the session and track it."""
        self.tasks.append(task)
        self.generated_task_ids.add(task["id"])

    def get_node_state(self, node: str) -> AreaState:
        """Return (and lazily create) the AreaState for a taxonomy node."""
        self._restore_node_beliefs()
        if node not in self.node_states:
            self.node_states[node] = AreaState()
        return self.node_states[node]

    def _restore_node_beliefs(self) -> None:
        """Restore persisted per-node statistics into a fresh session.

        Mirrors the global-ability restore in ``get_skill_state``: a session
        with no node evidence loads its own per-node sufficient statistics
        from ``user_skill_beliefs`` so mastery carries across sessions. Safe to
        call repeatedly (runs once).
        """
        if self._area_restored or self.node_states:
            return
        self._area_restored = True
        try:
            from coach.tasks import get_area_beliefs
            from coach.taxonomy import NODE_LEVEL

            for (level, key), b in get_area_beliefs(self.candidate).items():
                node_level = NODE_LEVEL.get(key)
                if node_level is None:
                    continue  # legacy/retired node — skip
                self.node_states[key] = AreaState(
                    mean=b["mean"],
                    variance=b["variance"],
                    questions_answered=b["questions_answered"],
                )
        except Exception:
            pass

    def attempts_for_node(self, task: dict) -> int:
        """Number of in-session observations for a task's primary skill."""
        tags = task.get("tags") or {}
        primary = tags.get("primary")
        if not primary:
            return 0
        return self.get_node_state(primary).questions_answered

    def previous_area(self) -> Optional[str]:
        """Primary area of the most recently asked task, if any."""
        asked = self.asked_task_ids
        for t in reversed(self.tasks):
            if t["id"] in asked:
                tags = t.get("tags") or {}
                return area_of(tags.get("primary"))
        return None

    def previous_domain(self) -> Optional[str]:
        """Primary domain of the most recently asked task, if any."""
        asked = self.asked_task_ids
        for t in reversed(self.tasks):
            if t["id"] in asked:
                tags = t.get("tags") or {}
                return domain_of(tags.get("primary"))
        return None

    def to_dict(self):
        """Compact episode-header state (trajectory lives in ``session_steps``).

        ``results`` and ``node_states`` are intentionally omitted: step data
        and per-node beliefs are persisted in ``session_steps`` /
        ``user_skill_beliefs``.
        """
        return {
            "candidate": self.candidate,
            "tasks": self.tasks,
            "index": self.index,
            "ability": self.ability.to_dict(),
            "asked_task_ids": list(self.asked_task_ids),
            "generated_task_ids": list(self.generated_task_ids),
            "task_progress": dict(self.task_progress),
            "phase_attempts": dict(self.phase_attempts),
            "submission_index": self.submission_index,
        }

    @classmethod
    def from_dict(cls, d):
        """Rebuild a Session from a compact (or legacy full) state dict.

        Tolerates legacy full-form blobs (``results``) so old rows keep
        working; the in-memory ``results`` are normally hydrated from
        ``session_steps`` afterwards.
        """
        s = cls(
            candidate=d.get("candidate", ""),
            tasks=d.get("tasks") or [],
            index=d.get("index", 0),
        )
        if isinstance(d.get("ability"), dict):
            s.ability = SkillState.from_dict(d["ability"])
        s.asked_task_ids = set(d.get("asked_task_ids", []) or [])
        s.generated_task_ids = set(d.get("generated_task_ids", []) or [])
        s.task_progress = {
            str(k): int(v) for k, v in (d.get("task_progress", {}) or {}).items()
        }
        s.phase_attempts = {
            str(k): int(v) for k, v in (d.get("phase_attempts", {}) or {}).items()
        }
        s.submission_index = int(d.get("submission_index", 0) or 0)
        for r in d.get("results") or []:
            try:
                s.results.append(EvaluationResult.from_dict(r))
            except Exception:
                pass
        # Per-node beliefs are loaded from user_skill_beliefs via
        # ensure_area_beliefs().
        return s


def _compose_step_scaffold(task: dict) -> str | None:
    """Compose a scaffold from step prompts when none is stored.

    One stub per step: ``def name(...)`` parsed from the step's prompt, or
    ``def {key}(*args): ...`` as a fallback.
    """
    parts = task.get("parts") or []
    if not parts:
        return None
    stubs: list[str] = []
    for part in parts:
        m = re.search(r"def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", part.get("prompt", ""))
        if m:
            name, params = m.group(1), m.group(2)
            stubs.append(f"def {name}({params}):\n    # TODO: implement {name}\n    pass\n")
        else:
            key = str(part.get("key") or "f")
            stubs.append(f"def {key}(*args):\n    # TODO: implement {key}\n    pass\n")
    return "\n\n".join(stubs)


def build_code_stub(task: dict) -> str | None:
    """Build an editor scaffold for a code task.

    A task that already carries a `scaffold` uses it; otherwise the scaffold
    is composed from the step prompts. Every task has at least one part, so
    there is no task-level-prompt fallback.
    """
    if task.get("scaffold"):
        return task["scaffold"]
    return _compose_step_scaffold(task)


def effective_parts(task: dict) -> list[dict]:
    """The task's steps (always one or more for a valid task).

    Every task is created with at least one part; a single-step question is a
    task with exactly one. There is no implicit/partless form.
    """
    return list(task.get("parts") or [])


def completed_phases(task: dict, session: Session) -> int:
    """Number of phases already passed for ``task`` in this session."""
    return int(session.task_progress.get(task.get("id"), 0) or 0)


def active_phase(task: dict, session: Session) -> Optional[dict]:
    """The active step for a task, or None when the task is complete."""
    parts = effective_parts(task)
    idx = completed_phases(task, session)
    if idx < 0 or idx >= len(parts):
        return None
    return parts[idx]


def _phase_scaffold(task: dict, part: dict) -> Optional[str]:
    """Starter code for one phase: its own scaffold, else a composed stub."""
    if part.get("scaffold"):
        return part["scaffold"]
    return _compose_step_scaffold({"parts": [part]})


def task_view(
    task: dict, session: Session, previous_code: Optional[str] = None
) -> dict | None:
    """Build the client-facing view of a task.

    Every task is step-by-step: the view emits only the active step plus
    ``phase_index``/``phase_total`` and its own scaffold, so the learner sees
    one step at a time with their prior code carried forward via
    ``previous_code``. Every task has at least one part.
    """
    if task is None:
        return None
    parts = effective_parts(task)
    active = active_phase(task, session)
    view = {
        "id": task["id"],
        "type": "code",
        # Derived from the first step; no authored overview is stored.
        "prompt": parts[0]["prompt"] if parts else task.get("prompt", ""),
        "difficulty": task.get("difficulty", 1),
        "max_score": task.get("max_score", 5),
        "scaffold": _phase_scaffold(task, active) if active else build_code_stub(task),
        "tags": task.get("tags") or {"primary": None, "secondary": []},
        "task_type": task.get("task_type") or "implement",
        "language": task.get("language") or "python",
    }
    if active:
        idx = completed_phases(task, session)
        view["delivery"] = "phased"
        view["phase_index"] = idx + 1
        view["phase_total"] = len(parts)
        view["parts"] = [active]
        view["max_score"] = int(active.get("max_score") or 5)
        if active.get("pass_score") is not None:
            view["pass_score"] = int(active.get("pass_score"))
    if previous_code:
        view["previous_code"] = previous_code
    if task.get("context_notes"):
        view["context_notes"] = task["context_notes"]
    if task.get("generated"):
        kind = str(task.get("generated_kind") or "remediate")
        label = {"remediate": "drill", "escalate": "escalation", "pivot": "pivot"}.get(kind, kind)
        view["remediation"] = {"focus": task.get("target_text"), "kind": label}
        if task.get("root_task_id"):
            view["remediation"]["root_task_id"] = task["root_task_id"]
    return view