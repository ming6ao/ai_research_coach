"""One-time map from the retired 2-level taxonomy to the current 3-level tree.

The previous vocabulary (11 families / 46 fine tags) is gone; this module maps
each retired tag to a leaf skill in ``coach.taxonomy`` (or ``DROP`` when the
topic was intentionally removed). It is a migration artifact used only by
``coach.migrate`` — it is **not** part of ``ALIASES`` (which stays focused on
LLM synonym robustness) and is never consulted at runtime.

Mapping policy:

- Frontier-relevant old tags map to the closest current leaf skill.
- Dated/generic content is dropped: classic tabular ML (``ml_classical``),
  tabular feature engineering, pandas/ETL plumbing, generic language drills,
  single-layer ``mlp``, and SHAP/LIME explainability.
"""

from __future__ import annotations

from typing import Optional

from coach.taxonomy import is_leaf

# ``None`` means the topic was intentionally removed — a task whose primary
# or part primary is unmappable has no home in the new taxonomy.
DROP: Optional[str] = None

OLD_TAG_MAP: dict[str, Optional[str]] = {
    # --- python (generic language drills: dropped) ---
    "data_structures": DROP,
    "functional": DROP,
    "generators_iterators": DROP,
    # --- data_etl (tabular plumbing: dropped) ---
    "pandas_cleaning": DROP,
    "joins_merges": DROP,
    "missing_outliers": DROP,
    # --- feature_eng (tabular feature engineering: dropped) ---
    "scaling_encoding": DROP,
    "feature_construction": DROP,
    "imbalanced_classes": DROP,
    # --- ml_classical (retired) ---
    "linear_regression": DROP,
    "classification_logistic": DROP,
    "trees_ensembles": DROP,
    "clustering_kmeans": DROP,
    "dimensionality_reduction": DROP,
    "knn_svm_naivebayes": DROP,
    # --- stats_probability ---
    "bias_variance": "optimization_theory",
    "distributions": "probability_statistics",
    "hypothesis_pvalue": "statistical_evaluation",
    "bayes_mle": "probability_statistics",
    "bootstrap_ci": "statistical_evaluation",
    # --- training ---
    "loss_functions": "pretraining_objectives",
    "regularization": "optimization_theory",
    "backprop": "calculus_autodiff",
    "lr_scheduling": "optimization_theory",
    "overfitting_underfitting": "error_analysis",
    # --- optimization ---
    "gradient_descent_sgd": "optimization_theory",
    "optimizers_adam": "optimization_theory",
    "hyperparameter_tuning": "experiment_design",
    # --- dl_arch ---
    "mlp": DROP,
    "cnn": "vision_encoders",
    "rnn_lstm": "state_space_models",
    "attention_transformer": "attention_variants",
    "activation_normalization": "normalization",
    # --- llm_genai ---
    "tokenization_bpe": "tokenizer_design",
    "pretraining_finetuning": "pretraining_objectives",
    "rag_retrieval": "retrieval_augmented_generation",
    "quantization": "quantization",
    "kv_cache": "kv_cache_management",
    # --- eval ---
    "metrics_classification": "benchmark_design",
    "regression_metrics": "statistical_evaluation",
    "cross_validation": "statistical_evaluation",
    "data_leakage_calibration": "contamination_detection",
    # --- mlops_serving ---
    "deployment_serving": "serving_engine_internals",
    "monitoring_drift": "monitoring_drift",
    "explainability": DROP,
    "reproducibility_tracking": "reproducibility_artifacts",
}

# The retired top-level family names (11). Old family-level belief rows cannot
# be mapped to a single new area/domain, so they are dropped and re-derived.
OLD_FAMILIES: frozenset[str] = frozenset(
    {
        "python",
        "data_etl",
        "feature_eng",
        "ml_classical",
        "stats_probability",
        "training",
        "optimization",
        "dl_arch",
        "llm_genai",
        "eval",
        "mlops_serving",
    }
)


def map_tag(name: Optional[str]) -> Optional[str]:
    """Map a retired tag name to a current leaf skill, or ``None`` (drop)."""
    if not name:
        return None
    key = str(name).strip().lower().replace("-", "_").replace(" ", "_")
    return OLD_TAG_MAP.get(key)


def map_secondary(names: Optional[list]) -> list[str]:
    """Map/dedupe a secondary tag list, silently dropping unmappable entries."""
    out: list[str] = []
    for raw in names or []:
        leaf = map_tag(raw)
        if leaf and leaf not in out:
            out.append(leaf)
    return out


def map_state(state: Optional[dict]) -> Optional[dict]:
    """Convert a legacy belief snapshot ``{global, families, tags}`` to ``{global, nodes}``.

    Legacy family-level stats are dropped (coarse; cannot be mapped to one
    area); legacy tag-level stats are rewritten to their mapped leaf skill.
    """
    if not isinstance(state, dict):
        return state
    if "nodes" in state or ("families" not in state and "tags" not in state):
        return state
    nodes: dict[str, dict] = {}
    for tag, st in (state.get("tags") or {}).items():
        leaf = map_tag(tag)
        if leaf is None:
            continue
        nodes[leaf] = st
    out = {"global": state.get("global")}
    out["nodes"] = nodes
    return out


def _self_check() -> None:
    """Fail fast if the map ever drifts from the current taxonomy."""
    for old, leaf in OLD_TAG_MAP.items():
        if leaf is not None and not is_leaf(leaf):
            raise AssertionError(f"OLD_TAG_MAP[{old!r}] -> {leaf!r} is not a leaf skill")
    if len(OLD_TAG_MAP) != 46:
        raise AssertionError(f"OLD_TAG_MAP should cover all 46 retired tags, got {len(OLD_TAG_MAP)}")


_self_check()
