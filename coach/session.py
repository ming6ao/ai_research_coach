import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from coach.area_score import AreaState
from coach.hints import select_hints
from coach.score import INITIAL_SCORE, INITIAL_VARIANCE, confidence_from_variance
from coach.judge import EvaluationResult
from coach.taxonomy import family_of


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
    """Gaussian belief over the candidate's overall ability plus metadata.

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
    skill_states: Dict[str, SkillState] = field(default_factory=dict)
    asked_task_ids: Set[str] = field(default_factory=set)
    viewed_hints: Dict[str, List[str]] = field(default_factory=dict)
    generated_task_ids: Set[str] = field(default_factory=set)
    family_states: Dict[str, AreaState] = field(default_factory=dict)
    tag_states: Dict[str, AreaState] = field(default_factory=dict)
    _area_restored: bool = field(default=False, init=False)

    def __post_init__(self):
        if not self.tasks:
            self.tasks = _load_bank_tasks(self.candidate)
        # Tolerate legacy sessions that stored per-skill dicts: collapse to
        # the single overall ability (prefer the most-answered entry).
        if self.skill_states and (
            self.ability.questions_answered == 0
            and self.ability.score == INITIAL_SCORE
            and self.ability.variance == INITIAL_VARIANCE
        ):
            try:
                best = max(
                    self.skill_states.values(),
                    key=lambda s: s.questions_answered,
                )
                self.ability = SkillState(
                    score=best.score,
                    variance=best.variance,
                    questions_answered=best.questions_answered,
                    evidence=list(best.evidence),
                    hints_used=list(best.hints_used),
                )
            except Exception:
                pass
            self.skill_states = {}

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
        """Load persisted per-family/tag statistics into this session."""
        self._restore_area_beliefs()

    def add_generated_task(self, task: dict) -> None:
        """Persist a generated remediation task in the session and track it."""
        self.tasks.append(task)
        self.generated_task_ids.add(task["id"])

    def get_family_state(self, family: str) -> AreaState:
        """Return (and lazily create) the AreaState for a family."""
        self._restore_area_beliefs()
        if family not in self.family_states:
            self.family_states[family] = AreaState()
        return self.family_states[family]

    def get_tag_state(self, tag: str) -> AreaState:
        """Return (and lazily create) the AreaState for a fine tag."""
        self._restore_area_beliefs()
        if tag not in self.tag_states:
            self.tag_states[tag] = AreaState()
        return self.tag_states[tag]

    def _restore_area_beliefs(self) -> None:
        """Restore persisted family/tag statistics into a fresh session.

        Mirrors the global-ability restore in ``get_skill_state``: a session
        with no area evidence loads its own (level, key) sufficient
        statistics from ``user_skill_beliefs`` so mastery carries across
        sessions. Safe to call repeatedly (runs once).
        """
        if self._area_restored or self.family_states or self.tag_states:
            return
        self._area_restored = True
        try:
            from coach.tasks import get_area_beliefs

            for (level, key), b in get_area_beliefs(self.candidate).items():
                st = AreaState(
                    mean=b["mean"],
                    variance=b["variance"],
                    questions_answered=b["questions_answered"],
                )
                if level == "family":
                    self.family_states[key] = st
                elif level == "tag":
                    self.tag_states[key] = st
        except Exception:
            pass

    def attempts_for_family(self, task: dict) -> int:
        """Number of in-session observations for a task's primary family."""
        tags = task.get("tags") or {}
        family = family_of(tags.get("primary")) or "python"
        return self.get_family_state(family).questions_answered

    def attempts_for_tag(self, task: dict) -> int:
        """Number of in-session observations for a task's primary tag."""
        tags = task.get("tags") or {}
        tag = tags.get("primary")
        if not tag:
            return 0
        return self.get_tag_state(tag).questions_answered

    def previous_family(self) -> Optional[str]:
        """Primary family of the most recently asked task, if any."""
        asked = self.asked_task_ids
        for t in reversed(self.tasks):
            if t["id"] in asked:
                tags = t.get("tags") or {}
                return family_of(tags.get("primary"))
        return None

    def to_dict(self):
        """Compact episode-header state (trajectory lives in ``session_steps``).

        ``results``, ``skill_states``, ``family_states``, and ``tag_states``
        are intentionally omitted: step data and per-level beliefs are
        persisted in ``session_steps`` / ``user_skill_beliefs``.
        """
        return {
            "candidate": self.candidate,
            "tasks": self.tasks,
            "index": self.index,
            "ability": self.ability.to_dict(),
            "asked_task_ids": list(self.asked_task_ids),
            "viewed_hints": self.viewed_hints,
            "generated_task_ids": list(self.generated_task_ids),
        }

    @classmethod
    def from_dict(cls, d):
        """Rebuild a Session from a compact (or legacy full) state dict.

        Tolerates legacy full-form blobs (results / skill_states /
        family_states / tag_states) so old rows keep working; the in-memory
        ``results`` are normally hydrated from ``session_steps`` afterwards.
        """
        s = cls(
            candidate=d.get("candidate", ""),
            tasks=d.get("tasks") or [],
            index=d.get("index", 0),
        )
        if isinstance(d.get("ability"), dict):
            s.ability = SkillState.from_dict(d["ability"])
        s.asked_task_ids = set(d.get("asked_task_ids", []) or [])
        s.viewed_hints = dict(d.get("viewed_hints", {}) or {})
        s.generated_task_ids = set(d.get("generated_task_ids", []) or [])
        for r in d.get("results") or []:
            try:
                s.results.append(EvaluationResult.from_dict(r))
            except Exception:
                pass
        # Legacy sessions without a compact ability snapshot collapse
        # skill_states into the overall ability (most-answered wins).
        if not isinstance(d.get("ability"), dict) and s.skill_states:
            try:
                best = max(
                    s.skill_states.values(),
                    key=lambda st: st.questions_answered,
                )
                s.ability = SkillState(
                    score=best.score,
                    variance=best.variance,
                    questions_answered=best.questions_answered,
                    evidence=list(best.evidence),
                    hints_used=list(best.hints_used),
                )
            except Exception:
                pass
            s.skill_states = {}
        s.family_states = {
            k: AreaState.from_dict(v) for k, v in (d.get("family_states", {}) or {}).items()
        }
        s.tag_states = {
            k: AreaState.from_dict(v) for k, v in (d.get("tag_states", {}) or {}).items()
        }
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
    ability = session.get_ability().score
    view = {
        "id": task["id"],
        "type": "code",
        "prompt": task["prompt"],
        "difficulty": task.get("difficulty", 1),
        "scaffold": build_code_stub(task),
        "hints": select_hints(task, ability),
        "tags": task.get("tags") or {"primary": "python", "secondary": []},
        "task_type": task.get("task_type") or "implement",
    }
    if task.get("context_notes"):
        view["context_notes"] = task["context_notes"]
    if task.get("generated"):
        kind = str(task.get("generated_kind") or "remediate")
        label = {"remediate": "drill", "escalate": "escalation", "pivot": "pivot"}.get(kind, kind)
        view["remediation"] = {"focus": task.get("target_text"), "kind": label}
        if task.get("root_task_id"):
            view["remediation"]["root_task_id"] = task["root_task_id"]
    return view