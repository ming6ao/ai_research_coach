"""Judge-driven adaptive follow-up loop (no knowledge graph).

After a candidate submits an answer, the judge's free-text gap
(``coach.misconception`` / ``coach.feedback``) decides whether a follow-up
task is warranted:

- Bank task failed (or solved with a named gap) -> simpler ``remediate`` drill.
- Solved drill -> harder ``escalate`` variant stepping back toward the root.
- Solved escalation -> ``pivot`` to a different prerequisite of the same root
  (grounded in ``context_notes``), then keep pivoting while solves continue.
- Still failing -> simpler drill again (bounded per-chain guard).

Sessions are open-ended: follow-ups keep the session going indefinitely and
``coach.selection`` generates fresh challenge tasks once the bank is
exhausted. Budget guards (a generous per-session cap + per-root chain cap)
keep the loop finite per root cause and hermetic-friendly.
"""

from __future__ import annotations

import logging
from typing import Optional

from coach.task_decomposer import TaskDecomposer

logger = logging.getLogger(__name__)

# --- Budget guards -----------------------------------------------------------
# Generous total cap so chains can escalate/pivot indefinitely in practice;
# per-root depth guard stops infinite loops on a single root task.
MAX_PER_SESSION = 30
MAX_CHAIN_PER_ROOT = 6

# Judge fraction below which an answer counts as not-solved.
CORRECT_AT = 0.8


class RemediationPlanner:
    """Decides whether (and how) to generate an adaptive follow-up task."""

    def __init__(
        self,
        decomposer: Optional[TaskDecomposer] = None,
        *,
        max_per_session: int = MAX_PER_SESSION,
        max_chain_per_root: int = MAX_CHAIN_PER_ROOT,
    ) -> None:
        self.decomposer = decomposer or TaskDecomposer()
        self.max_per_session = max_per_session
        self.max_chain_per_root = max_chain_per_root

    def decide(
        self,
        session,
        task: dict,
        result,
        coach,
    ) -> Optional[dict]:
        """Return a generated follow-up task dict, or None if unwarranted.

        ``session`` is the parent ``Session`` (budget cap + ability lookup).
        ``result`` is the judge ``EvaluationResult``; ``coach`` is the
        ``CoachContent`` (gap text source).
        """
        # 1. Budget guard (per-session cap).
        if self._session_generated_count(session) >= self.max_per_session:
            return None

        # 2. Judge signals.
        fraction = self._fraction(result)
        gap_text = self._gap_text(coach)
        if fraction is None:
            return None

        task = task or {}
        is_generated = bool(task.get("generated"))
        kind = str(task.get("generated_kind") or ("remediate" if is_generated else "bank"))
        root = self._root_task(session, task)
        root_id = root.get("id", task.get("id"))
        if self._chain_count(session, root_id) >= self.max_chain_per_root:
            return None

        # Challenge tasks behave like bank tasks: fail -> drill, solve -> stop
        # (selection will mint the next fresh challenge).
        if kind == "challenge":
            if fraction >= CORRECT_AT and not gap_text:
                return None
            difficulty = self._remediate_difficulty(session, task, fraction)
            return self._generate(
                session, task, root, gap_text or "the previous gap",
                difficulty, mode="remediate",
            )

        if not is_generated:
            # Bank/root task: unsolved, or solved with a named gap, -> drill.
            if fraction >= CORRECT_AT and not gap_text:
                return None
            difficulty = self._remediate_difficulty(session, task, fraction)
            return self._generate(
                session, task, root, gap_text or "the previous gap",
                difficulty, mode="remediate",
            )

        # Follow-up answered: adapt based on outcome.
        if fraction < CORRECT_AT:
            # Still struggling -> simpler drill on the current (or new) gap.
            difficulty = self._remediate_difficulty(session, task, fraction)
            return self._generate(
                session, task, root, gap_text or task.get("target_text") or "the previous gap",
                difficulty, mode="remediate",
            )

        # Solved follow-up -> progress the chain.
        if kind == "remediate":
            # Step back up toward the root difficulty.
            difficulty = self._escalate_difficulty(session, task, root)
            return self._generate(
                session, task, root, task.get("target_text") or gap_text or "the previous gap",
                difficulty, mode="escalate",
            )
        # Solved escalation (or pivot) -> pivot to a sibling prerequisite.
        # Keep pivoting while the candidate keeps solving.
        difficulty = self._pivot_difficulty(session, task, root)
        return self._generate(
            session, task, root, gap_text or "a related prerequisite of the root task",
            difficulty, mode="pivot",
        )

    def _generate(self, session, task: dict, root: dict, gap: str, difficulty: int, mode: str) -> dict:
        # Attach root metadata so the decomposer can bound difficulty and the
        # chain stays traceable; extra_context grounds pivots/escalations.
        base = dict(task or {})
        base["root_task_id"] = root.get("id", base.get("id"))
        base["root_difficulty"] = root.get("difficulty", base.get("difficulty", 2))
        extra = self._chain_context(session, root)
        generated = self.decomposer.generate_followup_task(
            gap, base, difficulty, mode=mode, extra_context=extra,
        )
        # Ensure bookkeeping survives decomposers that ignore it (e.g. fakes).
        generated.setdefault("generated_kind", mode)
        generated.setdefault("parent_task_id", (task or {}).get("id"))
        generated.setdefault("root_task_id", base["root_task_id"])
        generated.setdefault("root_difficulty", base["root_difficulty"])
        return generated

    # -- difficulty ----------------------------------------------------------

    def _ability_mean(self, session) -> float:
        try:
            return float(session.get_ability().score)
        except Exception:
            return 0.5

    def _remediate_difficulty(self, session, task: dict, fraction: float) -> int:
        """One step easier than the current task (two on very weak answers),
        then clamped so P(solve) lands near ~80% on overall ability alone."""
        from coach.solvability import TARGET_P_SOLVE, tune_difficulty_for_target

        base = max(1, min(5, int((task or {}).get("difficulty", 2))))
        difficulty = max(1, base - 1)
        if fraction < 0.4:
            difficulty = max(1, difficulty - 1)
        if fraction >= CORRECT_AT:
            # Consolidation repetition: same-or-easier, tuned to ~80% P(solve).
            try:
                difficulty = tune_difficulty_for_target(
                    self._ability_mean(session), None, None, base, TARGET_P_SOLVE
                )
            except Exception:
                difficulty = base
        return max(1, min(base, difficulty))

    def _escalate_difficulty(self, session, task: dict, root: dict) -> int:
        """One step harder than the solved drill, capped near the root level
        and tuned so P(solve) stays near ~80% (never above root+1 / 5)."""
        from coach.solvability import TARGET_P_SOLVE, tune_difficulty_for_target

        base = max(1, min(5, int((task or {}).get("difficulty", 2))))
        root_diff = max(1, min(5, int((root or {}).get("difficulty", base))))
        cap = max(base, min(5, root_diff + 1))
        # Prefer one step up, then tune to the hardest level meeting target.
        try:
            tuned = tune_difficulty_for_target(
                self._ability_mean(session), None, None, cap, TARGET_P_SOLVE,
                max_allowed=cap,
            )
            # Don't jump more than one step above the solved drill in one go
            # unless ability clearly supports it (tuned much higher).
            return max(base, min(cap, max(min(base + 1, cap), tuned) if tuned >= base else base))
        except Exception:
            return min(cap, base + 1)

    def _pivot_difficulty(self, session, task: dict, root: dict) -> int:
        """Hold near the last solved level (tuned to ~80% P(solve))."""
        from coach.solvability import TARGET_P_SOLVE, tune_difficulty_for_target

        base = max(1, min(5, int((task or {}).get("difficulty", 2))))
        try:
            tuned = tune_difficulty_for_target(
                self._ability_mean(session), None, None, base, TARGET_P_SOLVE,
                max_allowed=min(5, base + 1),
            )
            return max(1, min(5, tuned or base))
        except Exception:
            return base

    # -- chain helpers ---------------------------------------------------------

    @staticmethod
    def _root_task(session, task: dict) -> dict:
        """Follow ``parent_task_id`` links within the session to the root."""
        try:
            by_id = {t.get("id"): t for t in (getattr(session, "tasks", []) or [])}
            seen = set()
            cur = task or {}
            while cur.get("generated") and cur.get("parent_task_id") and cur["id"] not in seen:
                seen.add(cur.get("id"))
                parent = by_id.get(cur["parent_task_id"])
                if parent is None:
                    break
                cur = parent
            return cur
        except Exception:
            return task or {}

    def _chain_count(self, session, root_id: str) -> int:
        """Number of generated tasks in this root's chain."""
        try:
            count = 0
            for t in (getattr(session, "tasks", []) or []):
                if not t.get("generated"):
                    continue
                if t.get("root_task_id") == root_id or t.get("parent_task_id") == root_id:
                    count += 1
            return count
        except Exception:
            return 0

    def _chain_context(self, session, root: dict) -> str:
        """Root prompt + prerequisites + already-drilled gaps (anti-repeat)."""
        try:
            parts: list[str] = []
            if root.get("prompt"):
                parts.append(f"Root task: {str(root['prompt'])[:800]}")
            if root.get("context_notes"):
                parts.append(f"Prerequisites/context: {str(root['context_notes'])[:800]}")
            prior: list[str] = []
            root_id = root.get("id")
            for t in (getattr(session, "tasks", []) or []):
                if not t.get("generated"):
                    continue
                if t.get("root_task_id") == root_id or t.get("parent_task_id") == root_id:
                    label = str(t.get("target_text") or "").strip()
                    if label:
                        prior.append(f"- ({t.get('generated_kind', 'drill')}) {label[:160]}")
            if prior:
                parts.append("Already drilled (pick something different):\n" + "\n".join(prior[:8]))
            return "\n".join(parts)[:2000]
        except Exception:
            return ""

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _fraction(result) -> Optional[float]:
        try:
            if result is None:
                return None
            if isinstance(result, dict):
                max_score = result.get("max_score", 5) or 5
                return float(result.get("score", 0)) / max_score
            max_score = getattr(result, "max_score", 5) or 5
            return float(getattr(result, "score", 0)) / max_score
        except Exception:
            return None

    @staticmethod
    def _gap_text(coach) -> str:
        try:
            if coach is None:
                return ""
            if isinstance(coach, dict):
                return ((coach.get("misconception") or "").strip()
                        or (coach.get("feedback") or "").strip())
            return ((getattr(coach, "misconception", "") or "").strip()
                    or (getattr(coach, "feedback", "") or "").strip())
        except Exception:
            return ""

    @staticmethod
    def _session_generated_count(session) -> int:
        return len(getattr(session, "generated_task_ids", set()))


def plan_followup(
    session,
    task: dict,
    result,
    coach,
    planner: Optional[RemediationPlanner] = None,
) -> Optional[dict]:
    """Full post-submit follow-up: decide, generate, persist.

    Returns the generated task dict (already appended to ``session.tasks``)
    or None when no follow-up is warranted or generation fails. Failures
    are logged (including the raw model response, see
    ``TaskDecomposer.generate_followup_task``) and skipped so the main
    response is never broken — the session falls through to the bank picker.
    """
    try:
        planner = planner or RemediationPlanner()
        generated = planner.decide(session, task, result, coach)
        if generated is None:
            return None
        session.add_generated_task(generated)
        _persist_generated_task(session, generated, task)
        return generated
    except Exception as exc:
        logger.exception(
            "[followup] plan_followup failed for task=%s (%s: %s)",
            (task or {}).get("id"), type(exc).__name__, exc,
        )
        return None


def plan_challenge(
    session,
    planner: Optional[RemediationPlanner] = None,
    prefer_family: str = "",
    prefer_tag: str = "",
) -> Optional[dict]:
    """Mint a fresh adaptive task keeping an open-ended session going.

    Used when the bank is exhausted: difficulty tracks overall ability
    (~80% P(solve)), avoiding recently-drilled gaps. ``prefer_family`` /
    ``prefer_tag`` steer generation toward an under-explored area (scope
    widening, §5). Returns the generated task (appended to ``session.tasks``)
    or None on budget/generation failure.
    """
    try:
        planner = planner or RemediationPlanner()
        if planner._session_generated_count(session) >= planner.max_per_session:
            return None
        from coach.solvability import TARGET_P_SOLVE, tune_difficulty_for_target

        try:
            ability_mean = float(session.get_ability().score)
        except Exception:
            ability_mean = 0.5
        try:
            difficulty = tune_difficulty_for_target(
                ability_mean, None, None, 3, TARGET_P_SOLVE, max_allowed=5
            )
        except Exception:
            difficulty = 3
        recent: list[str] = []
        try:
            for t in (getattr(session, "tasks", []) or [])[-12:]:
                label = str((t or {}).get("target_text") or "").strip()
                if label:
                    recent.append(label[:160])
        except Exception:
            recent = []
        generated = _call_challenge(
            planner.decomposer,
            difficulty,
            avoid_text="\n".join(recent[:8]),
            prefer_family=prefer_family or "",
            prefer_tag=prefer_tag or "",
            tags=_target_tags(session, prefer_tag=prefer_tag, prefer_family=prefer_family),
        )
        session.add_generated_task(generated)
        _persist_generated_task(session, generated, None)
        return generated
    except Exception as exc:
        logger.exception("[challenge] plan_challenge failed (%s: %s)", type(exc).__name__, exc)
        return None


def _call_challenge(decomposer, difficulty, avoid_text="", prefer_family="", prefer_tag="", tags=None):
    """Call generate_challenge_task, passing only kwargs the decomposer accepts.

    Keeps fake/legacy decomposers (which lack the scope-targeting kwargs)
    working without weakening the real one.
    """
    import inspect

    sig = inspect.signature(decomposer.generate_challenge_task)
    params = set(sig.parameters)
    kwargs: dict = {}
    if "avoid_text" in params:
        kwargs["avoid_text"] = avoid_text
    if "prefer_family" in params:
        kwargs["prefer_family"] = prefer_family
    if "prefer_tag" in params:
        kwargs["prefer_tag"] = prefer_tag
    if "tags" in params:
        kwargs["tags"] = tags
    return decomposer.generate_challenge_task(difficulty, **kwargs)


def _target_tags(session, prefer_tag: str = "", prefer_family: str = "") -> dict | None:
    """Tags for a scope-widening challenge: prefer_tag primary, else family."""
    if prefer_tag:
        return {"primary": prefer_tag, "secondary": []}
    if prefer_family:
        return {"primary": prefer_family, "secondary": []}
    return None


def least_covered(session) -> tuple[str, str]:
    """Least-covered (family, tag) from in-session attempt counts (§5).

    Returns the tag with the fewest in-session observations (ties broken by
    family coverage then lexicographic order) and its family. Used to steer
    tag-directed generation when the bank has no eligible task.
    """
    from coach.taxonomy import ALL_TAGS, FAMILIES

    try:
        by_family = {
            fam: session.get_family_state(fam).questions_answered for fam in FAMILIES
        }
        best_family = min(FAMILIES, key=lambda f: (by_family[f], f))
        candidates = [t for t in ALL_TAGS if t in best_family]
        if not candidates:
            candidates = ALL_TAGS
        best_tag = min(
            candidates, key=lambda t: (session.get_tag_state(t).questions_answered, t)
        )
        return best_family, best_tag
    except Exception:
        return "python", "python"


def _persist_generated_task(session, generated: dict, parent_task: dict | None) -> None:
    """Best-effort persistence of generated tasks to the task bank."""
    try:
        from coach.tasks import create_task

        candidate = getattr(session, "candidate", "system")
        create_task(
            prompt=generated.get("prompt", ""),
            owner=candidate,
            scaffold=generated.get("scaffold"),
            difficulty=generated.get("difficulty", 2),
            max_score=generated.get("max_score", 5),
            hints=generated.get("hints", []),
            context_notes="",
            tags=generated.get("tags"),
            source="generated",
            parent_task_id=(parent_task or {}).get("id") or generated.get("parent_task_id"),
            target_text=generated.get("target_text"),
            is_public=False,
            task_id=generated.get("id"),
        )
    except Exception:
        pass
