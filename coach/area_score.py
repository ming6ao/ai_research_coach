"""Per-area (family/tag) Bayesian belief updates + read-time shrinkage.

Implements the hierarchical mastery estimator from the design doc §4:

- Each candidate keeps **per-level sufficient statistics** for the global
  estimate, each family, and each fine tag: ``mean`` (own observations),
  ``variance`` (posterior variance from a neutral prior updated only by
  observations *at that level*), and ``questions_answered``.
- At **read time** (progress view, picker, coverage report) the reported
  estimate is computed with an order-invariant empirical-Bayes fold:

      eta  = 2.0
      w(x) = n_x / (n_x + eta)

      reported_mu(level)  = w * mu_own + (1 - w) * parent_mu_shrunk
      reported_var(level) = (w^2 * var_own + (1-w)^2 * parent_var_shrunk)

  where the parent of a tag is its family's reported estimate and the
  parent of a family is the global reported estimate.

Consequences (all covered by tests):

- Unattempted tag (n=0 -> w=0) reports exactly its family's shrunk estimate.
- Sparse tag (1-2 attempts) reports mostly its family's estimate.
- Dense tag (n >> eta) converges to the candidate's own mean.
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
from coach.taxonomy import family_of

# Shrinkage strength: single knob for how quickly a level's own evidence
# outvotes its parent's estimate. Tuned against synthetic sequences in tests.
ETA = 2.0


@dataclass
class AreaState:
    """Own sufficient statistics for one level (global/family/tag).

    ``mean``/``variance`` hold only the observations *at this level* (a
    neutral prior updated by them); the reported (shrunk) estimate is
    computed at read time by ``reported`` / ``fold_reported``.
    """
    mean: float = INITIAL_SCORE
    variance: float = INITIAL_VARIANCE
    questions_answered: int = 0

    def update(self, difficulty: int, observation: float) -> "AreaState":
        """Update own statistics with one (hint-adjusted) observation.

        Measurement noise is difficulty-matched to this level's *own* mean
        (not the shrunk estimate), per §4.2.
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
    family_states: Dict[str, AreaState],
    tag_states: Dict[str, AreaState],
):
    """Read-time fold producing shrunk estimates for every level.

    Returns a tuple ``(global_report, family_reports, tag_reports)`` where
    each report is ``(mu, variance)``. ``global_report`` is the candidate's
    own global statistics (top of the hierarchy, no parent). Family reports
    use the global report as parent; tag reports use their family's report
    as parent (unknown family -> global).
    """
    g_mu, g_var = global_state.mean, global_state.variance
    family_reports: Dict[str, tuple[float, float]] = {}
    for fam, st in family_states.items():
        family_reports[fam] = reported(st, g_mu, g_var)
    tag_reports: Dict[str, tuple[float, float]] = {}
    for tag, st in tag_states.items():
        fam = family_of(tag)
        f_mu, f_var = family_reports.get(fam, (g_mu, g_var))
        tag_reports[tag] = reported(st, f_mu, f_var)
    return (g_mu, g_var), family_reports, tag_reports


def area_report_dict(
    global_state: AreaState,
    family_states: Dict[str, AreaState],
    tag_states: Dict[str, AreaState],
) -> dict:
    """Full mastery block: shrunk score + confidence + counts at every level.

    Includes all families and all fine tags; unattempted entries report
    their parent's shrunk estimate (never a blank bar / raw neutral prior).
    """
    from coach.score import confidence_from_variance
    from coach.taxonomy import ALL_TAGS, FAMILIES

    (g_mu, g_var), family_reports, tag_reports = fold_reported(
        global_state, family_states, tag_states
    )

    def _entry(mu: float, var: float, n: int) -> dict:
        return {
            "score": round(mu, 4),
            "confidence": round(confidence_from_variance(var), 4),
            "questions_answered": n,
        }

    mastery = {
        "global": _entry(g_mu, g_var, global_state.questions_answered),
        "families": {},
        "tags": {},
    }
    for fam in FAMILIES:
        st = family_states.get(fam, AreaState())
        mu, var = family_reports.get(fam, reported(st, g_mu, g_var))
        mastery["families"][fam] = _entry(mu, var, st.questions_answered)
    for tag in ALL_TAGS:
        st = tag_states.get(tag, AreaState())
        fam = family_of(tag)
        f_mu, f_var = family_reports.get(fam, (g_mu, g_var))
        mu, var = tag_reports.get(tag, reported(st, f_mu, f_var))
        mastery["tags"][tag] = _entry(mu, var, st.questions_answered)
        mastery["tags"][tag]["family"] = fam
    return mastery