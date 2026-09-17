"""Closed ML-topic vocabulary for task tagging.

Single source of truth for the tag/family taxonomy (the design doc
``docs/builtin-question-bank-and-mastery-design-v3.md``, §2). Every task
carries a ``tags`` block of the shape::

    {"primary": <fine tag>, "secondary": [<fine tag>, ...]}

with exactly one primary and 0-2 secondary tags. Each fine tag maps to
exactly one family (``TAG_TO_FAMILY``); no tag maps to more than one family.

``validate`` is the server-side gate: unknown tags are rejected (422 on
create/PATCH). Only the primary tag feeds the belief estimator; secondary
tags contribute to task diversity only.
"""

from __future__ import annotations

# Families (11) -> fine tags (46). The vocabulary is deliberately limited to
# code-gradable ML/AI topics; tasks are authored so the bank covers every
# family and every fine tag (the DB is the source of truth for tasks).
FAMILIES: list[str] = [
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
]

TAGS: dict[str, list[str]] = {
    "python": ["data_structures", "functional", "generators_iterators"],
    "data_etl": ["pandas_cleaning", "joins_merges", "missing_outliers"],
    "feature_eng": ["scaling_encoding", "feature_construction", "imbalanced_classes"],
    "ml_classical": [
        "linear_regression",
        "classification_logistic",
        "trees_ensembles",
        "clustering_kmeans",
        "dimensionality_reduction",
        "knn_svm_naivebayes",
    ],
    "stats_probability": [
        "bias_variance",
        "distributions",
        "hypothesis_pvalue",
        "bayes_mle",
        "bootstrap_ci",
    ],
    "training": [
        "loss_functions",
        "regularization",
        "backprop",
        "lr_scheduling",
        "overfitting_underfitting",
    ],
    "optimization": ["gradient_descent_sgd", "optimizers_adam", "hyperparameter_tuning"],
    "dl_arch": ["mlp", "cnn", "rnn_lstm", "attention_transformer", "activation_normalization"],
    "llm_genai": ["tokenization_bpe", "pretraining_finetuning", "rag_retrieval", "quantization", "kv_cache"],
    "eval": ["metrics_classification", "regression_metrics", "cross_validation", "data_leakage_calibration"],
    "mlops_serving": ["deployment_serving", "monitoring_drift", "explainability", "reproducibility_tracking"],
}

TAG_TO_FAMILY: dict[str, str] = {
    tag: family for family, tags in TAGS.items() for tag in tags
}

# Convenience canonical tag lists (validation/iteration).
ALL_TAGS: list[str] = [tag for tags in TAGS.values() for tag in tags]

# Synonym/alternate-name map -> canonical fine tag. Keeps LLM categorization
# and human entry robust to near-duplicate phrasing (one canonical tag per
# concept, §2 of the design).
ALIASES: dict[str, str] = {
    "data_structure": "data_structures",
    "collections": "data_structures",
    "functional_programming": "functional",
    "map_reduce": "functional",
    "generators": "generators_iterators",
    "iterators": "generators_iterators",
    "pandas": "pandas_cleaning",
    "data_cleaning": "pandas_cleaning",
    "merge": "joins_merges",
    "join": "joins_merges",
    "outliers": "missing_outliers",
    "imputation": "missing_outliers",
    "missing_data": "missing_outliers",
    "scaling": "scaling_encoding",
    "normalization": "scaling_encoding",
    "encoding": "scaling_encoding",
    "feature_engineering": "feature_construction",
    "feature_creation": "feature_construction",
    "class_imbalance": "imbalanced_classes",
    "resampling": "imbalanced_classes",
    "oversampling": "imbalanced_classes",
    "undersampling": "imbalanced_classes",
    "linear_model": "linear_regression",
    "regression": "linear_regression",
    "logistic": "classification_logistic",
    "logistic_regression": "classification_logistic",
    "classification": "classification_logistic",
    "decision_tree": "trees_ensembles",
    "random_forest": "trees_ensembles",
    "gradient_boosting": "trees_ensembles",
    "xgboost": "trees_ensembles",
    "ensemble": "trees_ensembles",
    "kmeans": "clustering_kmeans",
    "kmeans_clustering": "clustering_kmeans",
    "pca": "dimensionality_reduction",
    "svd": "dimensionality_reduction",
    "tsne": "dimensionality_reduction",
    "umap": "dimensionality_reduction",
    "knn": "knn_svm_naivebayes",
    "k_nearest": "knn_svm_naivebayes",
    "svm": "knn_svm_naivebayes",
    "naive_bayes": "knn_svm_naivebayes",
    "bias_variance_tradeoff": "bias_variance",
    "variance_bias": "bias_variance",
    "probability_distributions": "distributions",
    "distribution": "distributions",
    "pvalue": "hypothesis_pvalue",
    "p_value": "hypothesis_pvalue",
    "hypothesis_testing": "hypothesis_pvalue",
    "bayesian": "bayes_mle",
    "mle": "bayes_mle",
    "maximum_likelihood": "bayes_mle",
    "bootstrap": "bootstrap_ci",
    "confidence_interval": "bootstrap_ci",
    "loss": "loss_functions",
    "loss_function": "loss_functions",
    "cross_entropy": "loss_functions",
    "mse": "loss_functions",
    "regularizer": "regularization",
    "l2": "regularization",
    "l1": "regularization",
    "dropout": "regularization",
    "weight_decay": "regularization",
    "backpropagation": "backprop",
    "backpropogation": "backprop",
    "learning_rate_schedule": "lr_scheduling",
    "lr_schedule": "lr_scheduling",
    "learning_rate_decay": "lr_scheduling",
    "overfitting": "overfitting_underfitting",
    "underfitting": "overfitting_underfitting",
    "gradient_descent": "gradient_descent_sgd",
    "sgd": "gradient_descent_sgd",
    "stochastic_gradient_descent": "gradient_descent_sgd",
    "adam": "optimizers_adam",
    "optimizer": "optimizers_adam",
    "hyperparameters": "hyperparameter_tuning",
    "grid_search": "hyperparameter_tuning",
    "model_selection": "hyperparameter_tuning",
    "multilayer_perceptron": "mlp",
    "perceptron": "mlp",
    "neural_network": "mlp",
    "convolution": "cnn",
    "conv_net": "cnn",
    "rnn": "rnn_lstm",
    "lstm": "rnn_lstm",
    "attention": "attention_transformer",
    "transformer": "attention_transformer",
    "self_attention": "attention_transformer",
    "softmax": "activation_normalization",
    "activations": "activation_normalization",
    "batch_norm": "activation_normalization",
    "layer_norm": "activation_normalization",
    "tokenization": "tokenization_bpe",
    "bpe": "tokenization_bpe",
    "wordpiece": "tokenization_bpe",
    "tokenizer": "tokenization_bpe",
    "pretraining": "pretraining_finetuning",
    "fine_tuning": "pretraining_finetuning",
    "finetuning": "pretraining_finetuning",
    "rag": "rag_retrieval",
    "retrieval": "rag_retrieval",
    "vector_search": "rag_retrieval",
    "embeddings": "rag_retrieval",
    "quantize": "quantization",
    "quantization": "quantization",
    "kv_cache": "kv_cache",
    "key_value_cache": "kv_cache",
    "confusion_matrix": "metrics_classification",
    "precision_recall": "metrics_classification",
    "auc": "metrics_classification",
    "f1": "metrics_classification",
    "r2": "regression_metrics",
    "r_squared": "regression_metrics",
    "mae": "regression_metrics",
    "rmse": "regression_metrics",
    "cross_validation": "cross_validation",
    "kfold": "cross_validation",
    "k_fold": "cross_validation",
    "cv": "cross_validation",
    "leakage": "data_leakage_calibration",
    "data_leakage": "data_leakage_calibration",
    "calibration": "data_leakage_calibration",
    "deployment": "deployment_serving",
    "serving": "deployment_serving",
    "inference": "deployment_serving",
    "drift": "monitoring_drift",
    "monitoring": "monitoring_drift",
    "psi": "monitoring_drift",
    "ks": "monitoring_drift",
    "explainability": "explainability",
    "shap": "explainability",
    "lime": "explainability",
    "interpretability": "explainability",
    "reproducibility": "reproducibility_tracking",
    "experiment_tracking": "reproducibility_tracking",
    "mlflow": "reproducibility_tracking",
}

# Task types (each is still implemented as a code task judged normally).
TASK_TYPES = ("implement", "apply", "debug", "design", "analyze")

DEFAULT_TAGS: dict = {"primary": "python", "secondary": []}


def normalize_tag(tag: str) -> str | None:
    """Resolve an alias/spelling to a canonical fine tag, or None.

    A family name is accepted as its own "tag" so the design's default
    ``{"primary": "python", "secondary": []}`` and the no-key categorization
    fallback stay valid (a family primary feeds that family's belief).
    """
    if not tag:
        return None
    key = str(tag).strip().lower().replace("-", "_").replace(" ", "_")
    if key in TAG_TO_FAMILY:
        return key
    if key in FAMILIES:
        return key
    return ALIASES.get(key)


def is_valid_tag(tag: str) -> bool:
    return normalize_tag(tag) is not None


def is_valid_family(family: str) -> bool:
    return str(family).strip() in FAMILIES


def family_of(tag: str) -> str | None:
    """Return the family for a (possibly aliased) fine tag, or None.

    A family name maps to itself (``family_of("python") == "python"``).
    """
    canon = normalize_tag(tag)
    if canon is None:
        return None
    return TAG_TO_FAMILY.get(canon, canon if canon in FAMILIES else None)


def validate(tags: dict | None) -> dict:
    """Validate a tags block; returns the canonical normalized dict.

    Accepted shapes:
      ``{"primary": "tag", "secondary": ["tag", ...]}``  (0-2 secondary)
      ``None`` -> ``{"primary": "python", "secondary": []}``
      a plain string -> treated as the primary tag.

    Raises ``ValueError`` when a tag is unknown or the shape is invalid.
    """
    if tags is None:
        return dict(DEFAULT_TAGS)
    if isinstance(tags, str):
        tags = {"primary": tags, "secondary": []}
    if not isinstance(tags, dict):
        raise ValueError("tags must be an object {primary, secondary}.")
    primary_raw = tags.get("primary")
    if not primary_raw:
        raise ValueError("tags.primary is required.")
    primary = normalize_tag(primary_raw)
    if primary is None:
        raise ValueError(f"Unknown tag: {primary_raw!r}.")
    secondary_raw = tags.get("secondary") or []
    if not isinstance(secondary_raw, (list, tuple)):
        raise ValueError("tags.secondary must be a list.")
    if len(secondary_raw) > 2:
        raise ValueError("tags.secondary may have at most 2 tags.")
    secondary: list[str] = []
    for raw in secondary_raw:
        canon = normalize_tag(raw)
        if canon is None or canon in FAMILIES:
            raise ValueError(f"Unknown fine tag: {raw!r}.")
        if canon not in secondary:
            secondary.append(canon)
    if primary in secondary:
        secondary.remove(primary)
    return {"primary": primary, "secondary": secondary}