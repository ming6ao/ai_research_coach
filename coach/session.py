import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from coach.area_score import AreaState
from coach.score import INITIAL_SCORE, INITIAL_VARIANCE, confidence_from_variance
from coach.judge import EvaluationResult
from coach.taxonomy import family_of


def _load_bank_tasks(candidate: str) -> list:
    """Load the visible task bank from the DB.

    Tasks live in the ``tasks`` table (the DB is the source of truth; there
    is no code-embedded bank). An empty bank is valid (the UI prompts the user
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
    skill_states: Dict[str, SkillState] = field(default_factory=dict)
    asked_task_ids: Set[str] = field(default_factory=set)
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


def _compose_block_scaffold(task: dict) -> str | None:
    """Compose a task-level scaffold from part prompts when none is stored.

    One stub per part: ``def name(...)`` parsed from the part's prompt, or
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

    Scaffold-mode tasks already carry a `scaffold`. Code blocks without one
    get their scaffold composed per part. For function-mode tasks (no
    scaffold, no parts) we generate a stub from the signature mentioned in
    the prompt so the coding area is pre-filled instead of blank.
    """
    if task.get("scaffold"):
        return task["scaffold"]
    composed = _compose_block_scaffold(task)
    if composed:
        return composed
    m = re.search(r"def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", task.get("prompt", ""))
    if m:
        name, params = m.group(1), m.group(2)
        return f"def {name}({params}):\n    # TODO: implement {name}\n    pass\n"
    return None


def _version_total(task: dict, session: Session) -> int:
    """Total number of versions in this task's version chain."""
    root_id = task.get("version_root_id") or task.get("id")
    indexes = {
        (t.get("version_index") or 1)
        for t in session.tasks
        if (t.get("version_root_id") or t.get("id")) == root_id
    }
    return max(indexes) if indexes else 1


def task_view(
    task: dict, session: Session, previous_code: Optional[str] = None
) -> dict | None:
    """Build the client-facing view of a task.

    Code blocks emit their ``parts`` and aggregate ``max_score``; version
    successors additionally carry ``previous_code`` (the predecessor's
    submitted answer), ``version_index``, ``version_total``, and
    ``depends_on_task_id``.
    """
    if task is None:
        return None
    view = {
        "id": task["id"],
        "type": "code",
        "prompt": task["prompt"],
        "difficulty": task.get("difficulty", 1),
        "max_score": task.get("max_score", 5),
        "scaffold": build_code_stub(task),
        "tags": task.get("tags") or {"primary": "python", "secondary": []},
        "task_type": task.get("task_type") or "implement",
    }
    parts = task.get("parts") or []
    if parts:
        view["parts"] = parts
    if previous_code:
        view["previous_code"] = previous_code
    if task.get("version_index") and task["version_index"] > 1:
        view["version_index"] = task["version_index"]
        view["version_total"] = _version_total(task, session)
    if task.get("depends_on_task_id"):
        view["depends_on_task_id"] = task["depends_on_task_id"]
    if task.get("context_notes"):
        view["context_notes"] = task["context_notes"]
    if task.get("generated"):
        kind = str(task.get("generated_kind") or "remediate")
        label = {"remediate": "drill", "escalate": "escalation", "pivot": "pivot"}.get(kind, kind)
        view["remediation"] = {"focus": task.get("target_text"), "kind": label}
        if task.get("root_task_id"):
            view["remediation"]["root_task_id"] = task["root_task_id"]
    return view