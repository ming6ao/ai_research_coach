"""Qualitative regression checks for the replay harness (Stage 10).

Checks assert broad outcomes — never exact floating-point equality.
"""

from __future__ import annotations

from typing import Any

from ..domain.learner import StateStatus
from .models import ReplayReport


def _state(report: ReplayReport, slug: str):
    return report.states.get(slug)


def run_all(assertions: list[dict], report: ReplayReport, c, learner_id: Any) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for spec in assertions:
        kind = spec["kind"]
        check = _CHECKS.get(kind)
        if check is None:
            failures.append(f"unknown assertion kind: {kind}")
            continue
        if not check(spec, report, c, learner_id):
            failures.append(f"assertion failed: {spec}")
    return not failures, failures


# -- individual checks ---------------------------------------------------------


def _status(spec, report, c, learner_id):
    st = _state(report, spec["node"])
    return st is not None and st.status == spec["expect"]


def _mastery_above(spec, report, c, learner_id):
    st = _state(report, spec["node"])
    return st is not None and st.mastery > spec["value"]


def _mastery_below(spec, report, c, learner_id):
    st = _state(report, spec["node"])
    return st is not None and st.mastery < spec["value"]


def _uncertainty_below(spec, report, c, learner_id):
    st = _state(report, spec["node"])
    return st is not None and st.uncertainty < spec["value"]


def _evidence_count_above(spec, report, c, learner_id):
    return report.evidence_counts.get(spec["node"], 0) > spec["value"]


def _dimension_above(spec, report, c, learner_id):
    st = _state(report, spec["node"])
    if st is None:
        return False
    return getattr(st, spec["dimension"], 0.0) > spec["value"]


def _dimension_below(spec, report, c, learner_id):
    st = _state(report, spec["node"])
    if st is None:
        return False
    return getattr(st, spec["dimension"], 1.0) < spec["value"]


def _not_observed_not_incorrect(spec, report, c, learner_id):
    """A node with only not_observed evidence must never be 'incorrect'."""
    node = c.knowledge_repository.get_node_by_slug(spec["node"])
    if node is None:
        return False
    summary = c.evidence_service.summarize(learner_id, node.id)
    return summary.incorrect_count == 0


def _status_not(spec, report, c, learner_id):
    """Assert the node's status is NOT the given value (e.g. not incorrect/unknown)."""
    st = _state(report, spec["node"])
    return st is not None and st.status != spec["expect"]


def _frontier_includes(spec, report, c, learner_id):
    nodes = {f["node"] for f in report.frontier}
    return all(n in nodes for n in spec["nodes"])


def _frontier_excludes(spec, report, c, learner_id):
    nodes = {f["node"] for f in report.frontier}
    return all(n not in nodes for n in spec["nodes"])


def _frontier_rank_above(spec, report, c, learner_id):
    """Every node in spec['above'] must outrank every node in spec['below']."""
    rank = {f["node"]: i for i, f in enumerate(report.frontier)}
    for above in spec["above"]:
        for below in spec["below"]:
            if above not in rank or below not in rank:
                return False
            if rank[above] >= rank[below]:
                return False
    return True


def _action_not_targets(spec, report, c, learner_id):
    if not report.actions:
        return False
    top = report.actions[0]
    return top["node"] not in spec["nodes"]


def _action_targets_any(spec, report, c, learner_id):
    if not report.actions:
        return False
    top = report.actions[0]
    return top["node"] in spec["nodes"]


def _misconception_active(spec, report, c, learner_id):
    return any(
        m["node"] == spec["node"] and m["status"] in ("suspected", "confirmed", "resolving")
        for m in report.misconceptions
    )


def _misconception_confirmed(spec, report, c, learner_id):
    return any(m["node"] == spec["node"] and m["status"] == "confirmed" for m in report.misconceptions)


def _misconception_probe_action(spec, report, c, learner_id):
    return any(a["action_type"] == "misconception_probe" for a in report.actions)


_CHECKS = {
    "status": _status,
    "mastery_above": _mastery_above,
    "mastery_below": _mastery_below,
    "uncertainty_below": _uncertainty_below,
    "evidence_count_above": _evidence_count_above,
    "dimension_above": _dimension_above,
    "dimension_below": _dimension_below,
    "not_observed_not_incorrect": _not_observed_not_incorrect,
    "status_not": _status_not,
    "frontier_includes": _frontier_includes,
    "frontier_excludes": _frontier_excludes,
    "frontier_rank_above": _frontier_rank_above,
    "action_not_targets": _action_not_targets,
    "action_targets_any": _action_targets_any,
    "misconception_active": _misconception_active,
    "misconception_confirmed": _misconception_confirmed,
    "misconception_probe_action": _misconception_probe_action,
}