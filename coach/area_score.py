"""Per-node Bayesian belief updates + read-time hierarchical shrinkage.

Implements the hierarchical mastery estimator:

- Each candidate keeps **per-node sufficient statistics** for the global
  estimate plus every taxonomy node (domain, area, skill): ``mean`` (own
  observations), ``variance`` (posterior variance from a neutral prior
  updated only by observations *at that level*), and ``questions_answered``.
- At **read time** (progress view, picker) the reported estimate is computed
  with an order-invariant empirical-Bayes fold over the taxonomy tree:

      eta  = 2.0
      w(x) = n_x / (n_x + eta)

      reported_mu(node)  = w * mu_own + (1 - w) * parent_mu_shrunk
      reported_var(node) = w^2 * var_own + (1-w)^2 * parent_var_shrunk

  where the parent of a domain is the global estimate, the parent of an area
  is its domain's reported estimate, and the parent of a skill is its area's
  reported estimate. The fold is depth-generic: it walks the taxonomy in
  parent-before-child order, so adding a level is a taxonomy-only change.

Consequences:
- Unattempted skill (n=0 -> w=0) reports exactly its area's shrunk estimate.
- Sparse skill (1-2 attempts) reports mostly its area's estimate.
- Dense skill (n >> eta) converges to the candidate's own mean.
- The same answers in any order produce identical beliefs (no
  path-dependency): only the sufficient statistics matter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from coach.score import (
    INITIAL_SCORE,
    INITIAL_VARIANCE,
    bayesian_update,
    measurement_variance,
)
from coach.taxonomy import ALL_NODES, NODE_LEVEL, NODE_PARENT, path_of

# Shrinkage strength: single knob for how quickly a level's own evidence
# outvotes its parent's estimate. Tuned against synthetic sequences in tests.
ETA = 2.0


@dataclass
class AreaState:
    """Own sufficient statistics for one level (global/domain/area/skill).

    ``mean``/``variance`` hold only the observations *at this level* (a
    neutral prior updated by them); the reported (shrunk) estimate is
    computed at read time by ``reported`` / ``fold_reported``.
    """
    mean: float = INITIAL_SCORE
    variance: float = INITIAL_VARIANCE
    questions_answered: int = 0

    def update(self, difficulty: int, observation: float) -> "AreaState":
        """Update own statistics with one observation.

        Measurement noise is difficulty-matched to this level's *own* mean
        (not the shrunk estimate).
        """
        obs_variance = measurement_variance(difficulty, self.mean)
        new_mean, new_variance = bayesian_update(
            self.mean, self.variance, observation, obs_variance
        )
        return AreaState(
            mean=new_mean,
            variance=new_variance,
            questions_answered=self.questions_answered + 1,
        )

    def to_dict(self):
        return {
            "mean": self.mean,
            "variance": self.variance,
            "questions_answered": self.questions_answered,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "AreaState":
        d = d or {}
        return cls(
            mean=float(d.get("mean", INITIAL_SCORE)),
            variance=float(d.get("variance", INITIAL_VARIANCE)),
            questions_answered=int(d.get("questions_answered", 0)),
        )


def weight(n: int) -> float:
    """Empirical-Bayes weight on a level's own evidence."""
    n = max(0, int(n))
    return n / (n + ETA)


def reported(state: AreaState, parent_mean: float, parent_var: float) -> tuple[float, float]:
    """Shrunk (mu, variance) for one level given its parent's reported estimate."""
    w = weight(state.questions_answered)
    mu = w * state.mean + (1 - w) * parent_mean
    var = w * w * state.variance + (1 - w) * (1 - w) * parent_var
    return mu, var


def fold_reported(
    global_state: AreaState,
    node_states: Dict[str, AreaState],
):
    """Read-time fold producing shrunk estimates for every taxonomy node.

    ``node_states`` is keyed by canonical node id (domain/area/skill). Nodes
    absent from the mapping are treated as unattempted. Returns
    ``(global_report, node_reports)`` where each report is ``(mu, variance)``.
    """
    g_mu, g_var = global_state.mean, global_state.variance
    node_reports: Dict[str, tuple[float, float]] = {}
    # ALL_NODES is ordered domains -> areas -> skills, so a node's parent is
    # always resolved before the node itself.
    for node in ALL_NODES:
        parent = NODE_PARENT[node]
        if parent is None:
            pm, pv = g_mu, g_var
        else:
            pm, pv = node_reports.get(parent, (g_mu, g_var))
        st = node_states.get(node, AreaState())
        node_reports[node] = reported(st, pm, pv)
    return (g_mu, g_var), node_reports


def area_report_dict(
    global_state: AreaState,
    node_states: Dict[str, AreaState],
) -> dict:
    """Full mastery block: nested domain/area/skill tree + flat node map.

    Includes every taxonomy node; unattempted entries report their parent's
    shrunk estimate (never a blank bar / raw neutral prior).
    """
    from coach.score import confidence_from_variance
    from coach.taxonomy import DOMAINS, TAXONOMY

    (g_mu, g_var), node_reports = fold_reported(global_state, node_states)

    def _entry(mu: float, var: float, n: int) -> dict:
        return {
            "score": round(mu, 4),
            "confidence": round(confidence_from_variance(var), 4),
            "questions_answered": n,
        }

    def _node_entry(node: str) -> dict:
        st = node_states.get(node, AreaState())
        mu, var = node_reports.get(node, reported(st, g_mu, g_var))
        return _entry(mu, var, st.questions_answered)

    nodes_flat: dict[str, dict] = {}
    for node in ALL_NODES:
        entry = _node_entry(node)
        entry["level"] = NODE_LEVEL.get(node, 0)
        entry["parent"] = NODE_PARENT.get(node)
        nodes_flat[node] = entry

    domains: dict[str, dict] = {}
    for domain in DOMAINS:
        domain_entry = dict(_node_entry(domain))
        areas: dict[str, dict] = {}
        for area, skills in TAXONOMY[domain].items():
            area_entry = dict(_node_entry(area))
            area_entry["skills"] = {skill: _node_entry(skill) for skill in skills}
            areas[area] = area_entry
        domain_entry["areas"] = areas
        domains[domain] = domain_entry

    return {
        "global": _entry(g_mu, g_var, global_state.questions_answered),
        "domains": domains,
        "nodes": nodes_flat,
    }


def path_levels(node: str) -> list[str]:
    """Backwards-compatible helper: root-to-node path for a node."""
    return path_of(node)
