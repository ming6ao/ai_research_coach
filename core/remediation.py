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

from core.task_decomposer import TaskDecomposer

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
        carries per-node ``uncertainty``/``mastery`` keyed by slug. ``session`` is
        the parent ``Session`` (used for budget caps and to look up the source
        skill).
        """
        # 1. Budget guards (per-session and per-skill caps).
        if self._session_generated_count(session) >= self.max_per_session:
            return None
        skill_id = task.get("skill", "general")
        if self._skill_generated_count(session, skill_id) >= self.max_per_skill:
            return None

        # 2. Node states keyed by slug (for uncertainty lookup).
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
                "slug": action.get("slug"),
            }

        frontier = (learner_update or {}).get("frontier") or []
        ranked = sorted(
            frontier,
            key=lambda f: self._state_uncertainty(f.get("slug"), states) or 0.0,
            reverse=True,
        )
        for entry in ranked:
            u = self._state_uncertainty(entry.get("slug"), states)
            if u is not None and u >= self.uncertainty_remediate_at:
                return {"node_id": entry.get("node_id"), "slug": entry.get("slug")}
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
        slug = target.get("slug")
        uncertainty = self._state_uncertainty(slug, states)

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
    def _state_uncertainty(slug: Optional[str], states: dict) -> Optional[float]:
        if not slug:
            return None
        state = states.get(slug)
        if not state:
            return None
        u = state.get("uncertainty")
        return float(u) if u is not None else None

    @staticmethod
    def _node_dict(target: dict, states: dict) -> dict:
        slug = target.get("slug") or ""
        state = states.get(slug) or {}
        return {
            "slug": slug,
            "name": slug.replace("-", " ").title(),
            "description": state.get("status", ""),
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
            from core.learner_bridge import LearnerBridge

            bridge = LearnerBridge()
        if planner is None:
            planner = RemediationPlanner()

        generated = planner.decide(
            session, task, result, learner_update, learner_snapshot
        )
        if generated is None:
            return None

        bridge.bootstrap_generated_task(generated)
        session.add_generated_task(generated)
        return generated
    except Exception:
        return None
