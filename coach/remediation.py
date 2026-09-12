"""Iterative remediation loop for the learning-partner MVP.

After a candidate submits an answer, the parent app checks whether the
learner's knowledge graph still has an actionable gap. When it does, a
``RemediationPlanner`` generates a *simpler* task that drills into the
highest-information-gain frontier node and feeds it back through the same
judge -> evidence -> learner-model -> frontier loop, so each session is
iterative until the relevant nodes are confident.

The decision to remediate is driven entirely by the MVP learner model:
- an incorrect / partially-correct answer, or
- a knowledge node with high uncertainty, or
- an active misconception.

The target node is the policy-ranked frontier top (maximizes expected
information gain). Budget guards keep the loop finite and hermetic-friendly.
"""

from __future__ import annotations

import os
import uuid
from typing import Optional

from coach.task_decomposer import TaskDecomposer

# --- Budget guards -----------------------------------------------------------
MAX_PER_SKILL = 2
MAX_PER_SESSION = 4
# Above this node uncertainty we consider the belief not yet pinned down.
UNCERTAINTY_REMEDIATE_AT = 0.35
# Below this we consider the node confident enough to stop remediating it.
UNCERTAINTY_STOP_AT = 0.15

# Incorrect / partially-correct statuses from the MVP observation mapping.
# These are the fraction bands used by LearnerBridge._observation_status.
INCORRECT_BELOW = 0.4
CORRECT_AT = 0.8


class RemediationPlanner:
    """Decides whether (and how) to generate a simpler follow-up task."""

    def __init__(
        self,
        decomposer: Optional[TaskDecomposer] = None,
        *,
        max_per_skill: int = MAX_PER_SKILL,
        max_per_session: int = MAX_PER_SESSION,
        uncertainty_remediate_at: float = UNCERTAINTY_REMEDIATE_AT,
        uncertainty_stop_at: float = UNCERTAINTY_STOP_AT,
    ) -> None:
        self.decomposer = decomposer or TaskDecomposer()
        self.max_per_skill = max_per_skill
        self.max_per_session = max_per_session
        self.uncertainty_remediate_at = uncertainty_remediate_at
        self.uncertainty_stop_at = uncertainty_stop_at

    def decide(
        self,
        session,
        task: dict,
        result,
        learner_update: dict,
        learner_snapshot: dict,
    ) -> Optional[dict]:
        """Return a generated remediation task dict, or None if none is warranted.

        ``learner_update`` is the value returned by
        ``LearnerBridge.record_submission`` (contains ``frontier``,
        ``next_action``, ``observation_status``, ``fraction``). ``learner_snapshot``
        carries per-node ``uncertainty``/``mastery`` keyed by node id. ``session`` is
        the parent ``Session`` (used for budget caps and to look up the source
        skill).
        """
        # 1. Budget guards (per-session and per-skill caps).
        if self._session_generated_count(session) >= self.max_per_session:
            return None
        skill_id = task.get("skill", "general")
        if self._skill_generated_count(session, skill_id) >= self.max_per_skill:
            return None

        # 2. Node states keyed by node id (for uncertainty lookup).
        states = (learner_snapshot or {}).get("states") or {}

        # 3. Pick a target node: the policy-ranked frontier top first, then the
        #    highest-uncertainty frontier node.
        target = self._pick_target(learner_update, states)
        if target is None:
            return None

        # 4. Decide whether this target is actually actionable.
        if not self._is_actionable(
            task,
            learner_update,
            learner_snapshot,
            target,
            states,
        ):
            return None

        # 5. Generate the simpler task for that node.
        node = self._node_dict(target, states)
        generated = self.decomposer.generate_remediation_task(
            node,
            task,
            self._fraction(learner_update),
        )
        generated["skill"] = skill_id
        return generated

    # -- target selection ------------------------------------------------------

    def _pick_target(
        self, learner_update: dict, states: dict
    ) -> Optional[dict]:
        """Choose the node to drill: next_action target, else max-uncertainty."""
        action = (learner_update or {}).get("next_action")
        if action:
            return {
                "node_id": action.get("target_node_id"),
                "name": action.get("name"),
                "description": action.get("description"),
            }

        frontier = (learner_update or {}).get("frontier") or []
        ranked = sorted(
            frontier,
            key=lambda f: self._state_uncertainty(f.get("node_id"), states) or 0.0,
            reverse=True,
        )
        for entry in ranked:
            u = self._state_uncertainty(entry.get("node_id"), states)
            if u is not None and u >= self.uncertainty_remediate_at:
                return {
                    "node_id": entry.get("node_id"),
                    "name": entry.get("name"),
                    "description": entry.get("description"),
                }
        return None

    # -- actionability -----------------------------------------------------------

    def _is_actionable(
        self,
        task: dict,
        learner_update: dict,
        learner_snapshot: dict,
        target: dict,
        states: dict,
    ) -> bool:
        """True when remediation is warranted for this target."""
        node_id = target.get("node_id")
        uncertainty = self._state_uncertainty(node_id, states)

        # Stop once the node is confident.
        if uncertainty is not None and uncertainty < self.uncertainty_stop_at:
            return False

        status = (learner_update or {}).get("observation_status")
        fraction = self._fraction(learner_update)

        # Incorrect / partially-correct answer -> remediate.
        if status in ("incorrect", "partially_correct"):
            return True
        if fraction is not None and fraction < CORRECT_AT:
            return True

        # An active misconception warrants remediation regardless of score.
        if self._has_active_misconception(learner_snapshot):
            return True

        # High uncertainty on the target node -> remediate.
        if uncertainty is not None and uncertainty >= self.uncertainty_remediate_at:
            return True

        return False

    # -- helpers ------------------------------------------------------------------

    @staticmethod
    def _fraction(learner_update: dict) -> Optional[float]:
        frac = (learner_update or {}).get("fraction")
        return float(frac) if frac is not None else None

    @staticmethod
    def _has_active_misconception(learner_snapshot: dict) -> bool:
        return bool((learner_snapshot or {}).get("misconceptions"))

    @staticmethod
    def _state_uncertainty(node_id: Optional[str], states: dict) -> Optional[float]:
        if not node_id:
            return None
        state = states.get(str(node_id))
        if not state:
            return None
        u = state.get("uncertainty")
        return float(u) if u is not None else None

    @staticmethod
    def _node_dict(target: dict, states: dict) -> dict:
        node_id = target.get("node_id") or ""
        state = states.get(str(node_id)) or {}
        name = target.get("name") or "this topic"
        description = target.get("description")
        if not description:
            description = state.get("status", "")
        return {
            "node_id": node_id,
            "name": name,
            "description": description,
        }

    @staticmethod
    def _session_generated_count(session) -> int:
        return len(getattr(session, "generated_task_ids", set()))

    @staticmethod
    def _skill_generated_count(session, skill_id: str) -> int:
        # Count generated tasks in the session matching the skill.
        count = 0
        for t in getattr(session, "tasks", []):
            if t.get("generated") and t.get("skill") == skill_id:
                count += 1
        return count


def plan_remediation(
    session,
    task: dict,
    result,
    learner_update: dict,
    learner_snapshot: dict,
    bridge=None,
    planner: Optional[RemediationPlanner] = None,
) -> Optional[dict]:
    """Full post-submit remediation: decide, generate, bootstrap, persist.

    Returns the generated task dict (already registered in the MVP and appended
    to ``session.tasks``) or None when no remediation is warranted. ``bridge``
    defaults to a fresh ``LearnerBridge``; ``planner`` defaults to a fresh
    ``RemediationPlanner``.

    Idempotent and non-fatal: returns None on any MVP/decomposition error so the
    main response is never broken.
    """
    try:
        if bridge is None:
            from learner.engine import LearnerEngine

            bridge = LearnerEngine()
        if planner is None:
            planner = RemediationPlanner()

        generated = planner.decide(
            session, task, result, learner_update, learner_snapshot
        )
        if generated is None:
            return None

        bridge.bootstrap_generated_task(generated)
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
            skill=generated.get("skill", "general"),
            owner=candidate,
            difficulty=generated.get("difficulty", 2),
            max_score=generated.get("max_score", 5),
            hints=generated.get("hints", []),
            source="generated",
            parent_task_id=(parent_task or {}).get("id"),
            target_node_id=generated.get("mvp_target_node_id"),
            is_public=False,
            task_id=generated.get("id"),
        )
    except Exception:
        pass


def plan_consolidation(
    session,
    task: dict,
    result,
    learner_update: dict,
    learner_snapshot: dict,
    bridge=None,
) -> Optional[dict]:
    """Generate a similar, high-solvability follow-up after a strong answer.

    Adaptive ladder: only fires when the candidate solved the task
    (fraction >= 0.8) but the target node belief is not yet confident, so
    one more near-transfer repetition consolidates mastery at ~80% P(solve).
    Shares the remediation budget caps. Returns the generated task or None.
    """
    try:
        from coach.solvability import TARGET_P_SOLVE, p_solve, tune_difficulty_for_target

        fraction = (learner_update or {}).get("fraction")
        if fraction is None and result is not None:
            max_score = getattr(result, "max_score", 5) or 5
            fraction = getattr(result, "score", 0) / max_score
        if fraction is None or float(fraction) < 0.8:
            return None

        if RemediationPlanner._session_generated_count(session) >= MAX_PER_SESSION:
            return None
        skill_id = task.get("skill", "general")
        if RemediationPlanner._skill_generated_count(session, skill_id) >= MAX_PER_SKILL:
            return None

        states = (learner_snapshot or {}).get("states") or {}
        action = (learner_update or {}).get("next_action") or {}
        node_id = action.get("target_node_id")
        target = None
        if node_id:
            target = {
                "node_id": node_id,
                "name": action.get("name"),
                "description": action.get("description"),
            }
        else:
            frontier = (learner_update or {}).get("frontier") or []
            if frontier:
                target = {
                    "node_id": frontier[0].get("node_id"),
                    "name": frontier[0].get("name"),
                    "description": frontier[0].get("description"),
                }
        if not target or not target.get("node_id"):
            return None

        state = states.get(str(target["node_id"])) or {}
        uncertainty = state.get("uncertainty")
        mastery = state.get("mastery")
        # Confident already -> no consolidation needed.
        if uncertainty is not None and float(uncertainty) < UNCERTAINTY_STOP_AT:
            return None
        # Nothing to consolidate when there is no uncertainty signal at all.
        if uncertainty is None and not (learner_snapshot or {}).get("misconceptions"):
            # Still allow one consolidation when frontier exists but state missing.
            uncertainty = 0.5

        skill_mean = 0.5
        try:
            skill_mean = session.get_skill_state(skill_id).score
        except Exception:
            pass
        base = max(1, min(5, int(task.get("difficulty", 2))))
        difficulty = tune_difficulty_for_target(
            skill_mean, mastery, uncertainty, base, TARGET_P_SOLVE
        )
        # Never harder than the solved task; ensure P(solve) in band.
        if p_solve(skill_mean, mastery, uncertainty, difficulty) < 0.7:
            difficulty = max(1, difficulty - 1)

        if bridge is None:
            from learner.engine import LearnerEngine

            bridge = LearnerEngine()
        node = RemediationPlanner._node_dict(target, states)
        generated = bridge.decomposer.generate_variant_task(node, task, difficulty)
        generated["skill"] = skill_id
        bridge.bootstrap_generated_task(generated)
        session.add_generated_task(generated)
        _persist_generated_task(session, generated, task)
        return generated
    except Exception:
        return None
