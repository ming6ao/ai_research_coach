"""Judge-driven follow-up loop (no knowledge graph).

After a candidate submits an answer, the judge's free-text gap
(``coach.misconception`` / ``coach.feedback``) decides whether a simpler
follow-up task is warranted. A low score or a named gap generates one
simpler drill task; strong clean answers generate nothing. Budget guards
keep the loop finite and hermetic-friendly.
"""

from __future__ import annotations

from typing import Optional

from coach.task_decomposer import TaskDecomposer

# --- Budget guards -----------------------------------------------------------
MAX_PER_SESSION = 4

# Judge fraction below which an answer counts as not-solved.
CORRECT_AT = 0.8


class RemediationPlanner:
    """Decides whether (and how) to generate a simpler follow-up task."""

    def __init__(
        self,
        decomposer: Optional[TaskDecomposer] = None,
        *,
        max_per_session: int = MAX_PER_SESSION,
    ) -> None:
        self.decomposer = decomposer or TaskDecomposer()
        self.max_per_session = max_per_session

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

        # 3. Trigger: unsolved answer, or any named gap even on a solve
        #    (one consolidation repetition, never harder than the original).
        if fraction is None:
            return None
        if fraction >= CORRECT_AT and not gap_text:
            return None

        difficulty = self._difficulty(session, task, fraction)
        generated = self.decomposer.generate_followup_task(gap_text or "the previous gap", task, difficulty)
        return generated

    # -- difficulty ----------------------------------------------------------

    def _difficulty(self, session, task: dict, fraction: float) -> int:
        """One step easier than the original (two on very weak answers),
        then clamped so P(solve) lands near ~80% on overall ability alone."""
        base = max(1, min(5, int((task or {}).get("difficulty", 2))))
        difficulty = max(1, base - 1)
        if fraction < 0.4:
            difficulty = max(1, difficulty - 1)
        if fraction >= CORRECT_AT:
            # Consolidation repetition: same-or-easier, tuned to ~80% P(solve).
            try:
                from coach.solvability import TARGET_P_SOLVE, p_solve, tune_difficulty_for_target

                ability_mean = 0.5
                try:
                    ability_mean = session.get_ability().score
                except Exception:
                    pass
                difficulty = tune_difficulty_for_target(ability_mean, None, None, base, TARGET_P_SOLVE)
                if p_solve(ability_mean, None, None, difficulty) < 0.7:
                    difficulty = max(1, difficulty - 1)
            except Exception:
                difficulty = base
        return max(1, min(base, difficulty))

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
    or None when no follow-up is warranted. Non-fatal: returns None on any
    error so the main response is never broken.
    """
    try:
        planner = planner or RemediationPlanner()
        generated = planner.decide(session, task, result, coach)
        if generated is None:
            return None
        session.add_generated_task(generated)
        _persist_generated_task(session, generated, task)
        return generated
    except Exception:
        return None


def _persist_generated_task(session, generated: dict, parent_task: dict | None) -> None:
    """Best-effort persistence of generated tasks to the task bank."""
    try:
        from coach.tasks import create_task

        candidate = getattr(session, "candidate", "system")
        create_task(
            prompt=generated.get("prompt", ""),
            owner=candidate,
            difficulty=generated.get("difficulty", 2),
            max_score=generated.get("max_score", 5),
            hints=generated.get("hints", []),
            context_notes="",
            source="generated",
            parent_task_id=(parent_task or {}).get("id"),
            target_text=generated.get("target_text"),
            is_public=False,
            task_id=generated.get("id"),
        )
    except Exception:
        pass
