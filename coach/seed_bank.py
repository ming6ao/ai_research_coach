"""Builtin ML question bank + coverage reporting + gap-filling CLI.

Implements the design doc §2 (block-versioned tasks):

- ``SEED_CATALOG``: code-block tasks. A block is one task-level ``scaffold``
  covering a set of related functions (``parts``); each part keeps its own
  tags, ``max_score``, and ``difficulty``. The 30 legacy single-function seeds
  regroup into **13 blocks + 3 versioned chains** whose parts cover every
  family and every fine tag. ``context_notes`` are pre-authored (no
  LLM/network at seed time).
- Versioned successors are separate catalog entries linked via
  ``depends_on`` (slug): the row gets ``depends_on_task_id`` +
  ``version_root_id`` and ``version_index = 2``.
- ``seed_question_bank()``: idempotent, hermetic, single-batched-transaction
  seeding (``INSERT OR IGNORE``) into the ``tasks`` table, plus stale-seed
  cleanup (``source='seed'`` rows whose id is not in the catalog are deleted).
  A human-edited seed row is never overwritten; content fixes bump the slug.
- ``coverage_report()``: per-family/per-tag seed coverage (primary or
  secondary on any seed **or part**) + per-candidate asked counts.
- ``--fill-gaps`` CLI: mints tasks for uncovered/lowest-coverage tags via
  tag-directed LLM generation (``coach.task_decomposer.generate_seed_task_for_tag``),
  persisted as ``source="seed_llm"``, ``is_public=1``.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from coach.taxonomy import ALL_TAGS, FAMILIES, TAG_TO_FAMILY

SYSTEM_OWNER = "system"


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _derive_tags(seed: dict[str, Any]) -> dict:
    """Block-level tags: explicit tags win; else derive from part primaries."""
    if seed.get("tags"):
        return seed["tags"]
    primaries = [p["tags"]["primary"] for p in (seed.get("parts") or [])]
    if not primaries:
        return {"primary": "python", "secondary": []}
    primary = primaries[0]
    secondary: list[str] = []
    for tag in primaries[1:]:
        if tag != primary and tag not in secondary:
            secondary.append(tag)
    return {"primary": primary, "secondary": secondary[:2]}


# Each catalog entry is a code block: slug, prompt, scaffold (covering all
# parts), parts [{key, prompt, tags, max_score, difficulty}], difficulty,
# max_score (sum of parts), task_type, context_notes (2-4 sentences). Version
# successors add ``depends_on`` (the predecessor's slug) and their own prompt/
# scaffold/tags. Authoring rule (enforced by review, not code): every part is
# self-contained, deterministic, and gradeable by the existing code judge.
SEED_CATALOG: list[dict[str, Any]] = [
    {
        "slug": "transformer_decode",
        "prompt": (
            "Implement the pieces of a small transformer decoding module: a numerically "
            "stable softmax and log_softmax, a single scaled dot-product attention head, "
            "and incremental decoding that keeps a key/value cache."
        ),
        "scaffold": (
            "def softmax(logits: list[float]) -> list[float]:\n"
            "    # TODO: numerically stable softmax\n"
            "    pass\n\n\n"
            "def log_softmax(logits: list[float]) -> list[float]:\n"
            "    # TODO: numerically stable log-softmax\n"
            "    pass\n\n\n"
            "import numpy as np\n\n\n"
            "def attention(q: np.ndarray, k: np.ndarray, v: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:\n"
            "    # TODO: return context vectors shape (n, d)\n"
            "    pass\n\n\n"
            "def decode_step(q: np.ndarray, k_new: np.ndarray, v_new: np.ndarray, k_cache: np.ndarray | None, v_cache: np.ndarray | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:\n"
            "    # TODO: return (context, k_cache, v_cache)\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "softmax",
                "prompt": (
                    "Implement a numerically stable softmax for a list of logits. Subtract "
                    "the max logit before exponentiating to avoid overflow, and return "
                    "probabilities that sum to 1.0 within floating point tolerance."
                ),
                "tags": {"primary": "activation_normalization", "secondary": ["loss_functions"]},
                "max_score": 5,
                "difficulty": 2,
            },
            {
                "key": "log_softmax",
                "prompt": (
                    "Implement a numerically stable log_softmax for a list of logits. "
                    "Compute it directly as x - max - log(sum(exp(x - max))) so very "
                    "negative inputs do not underflow."
                ),
                "tags": {"primary": "activation_normalization", "secondary": ["loss_functions"]},
                "max_score": 5,
                "difficulty": 2,
            },
            {
                "key": "attention",
                "prompt": (
                    "Implement a single scaled dot-product attention head. Given query, key, "
                    "value matrices each of shape (n, d) and an optional boolean mask of "
                    "shape (n, n), compute scores = Q @ K.T / sqrt(d), set masked positions "
                    "to a very negative number, softmax over the last axis, and return the "
                    "context vectors = attention @ V of shape (n, d)."
                ),
                "tags": {"primary": "attention_transformer", "secondary": ["kv_cache"]},
                "max_score": 5,
                "difficulty": 4,
            },
            {
                "key": "kv_cache",
                "prompt": (
                    "Implement incremental attention decoding with a key/value cache. Given a "
                    "new query token q, the new key k_new and value v_new, and the cached "
                    "keys/values for prior tokens (or None on the first step), append the "
                    "new key and value to the cache, then compute the scaled dot-product "
                    "attention of the single new query over all cached tokens (including the "
                    "new one). Return (context_vector, k_cache, v_cache)."
                ),
                "tags": {"primary": "kv_cache", "secondary": ["attention_transformer"]},
                "max_score": 5,
                "difficulty": 4,
            },
        ],
        "difficulty": 4,
        "max_score": 20,
        "task_type": "implement",
        "context_notes": (
            "Transformers decode one token at a time and each new token attends to every prior "
            "token. The softmax converts logits into a probability distribution (stable "
            "versions subtract the max to avoid overflow/underflow), and scaled dot-product "
            "attention combines queries, keys, and values with sqrt(d) scaling. Because each "
            "query only needs the keys and values, caching them across steps makes decoding "
            "linear instead of quadratic. Log-softmax is the underflow-safe companion to "
            "softmax used inside cross-entropy losses."
        ),
    },
    {
        "slug": "transformer_decode_mask",
        "depends_on": "transformer_decode",
        "prompt": (
            "Extend the attention implementation you wrote for the transformer block so it "
            "supports causal masking. Modify the attention function to accept a ``mask`` "
            "argument: positions where the mask is False (or 0) must be set to a very "
            "negative number before the softmax so future tokens cannot attend to "
            "themselves. Implement the mask as an (n, n) boolean array where True means "
            "allowed, and apply it before computing the attention weights."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def attention(q: np.ndarray, k: np.ndarray, v: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:\n"
            "    # TODO: apply the causal mask before the softmax\n"
            "    pass\n"
        ),
        "difficulty": 4,
        "max_score": 5,
        "tags": {"primary": "attention_transformer", "secondary": ["kv_cache"]},
        "task_type": "implement",
        "context_notes": (
            "Causal masking stops each token from attending to future positions, which is what "
            "makes a decoder autoregressive. The mask is applied to the raw attention scores "
            "(a very negative value collapses to probability zero through the softmax), never "
            "after normalization. This builds directly on the scaled dot-product attention "
            "you implemented first and is a common production requirement for generation."
        ),
    },
    {
        "slug": "training_step",
        "prompt": (
            "Implement the machinery of one neural-network training step: a backpropagation "
            "update for a 2-layer MLP, one Adam optimizer update, and a cosine-annealing "
            "learning-rate schedule with linear warm-up."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def bp_step(x: np.ndarray, y: float, W1: np.ndarray, b1: np.ndarray, W2: np.ndarray, b2: np.ndarray, lr: float = 0.1) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:\n"
            "    # TODO: return updated (W1, b1, W2, b2)\n"
            "    pass\n\n\n"
            "def adam_step(param: float, grad: float, m: float, v: float, t: int, lr: float = 0.001, beta1: float = 0.9, beta2: float = 0.999, eps: float = 1e-8) -> tuple[float, float, float]:\n"
            "    # TODO: return (param_new, m_new, v_new)\n"
            "    pass\n\n\n"
            "import math\n\n\n"
            "def lr_at_step(t: int, total_steps: int, warmup_steps: int, lr_init: float = 0.001, lr_final: float = 0.0) -> float:\n"
            "    # TODO: return learning rate at step t\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "bp_step",
                "prompt": (
                    "Implement one training step of backpropagation for a 2-layer MLP: a sigmoid "
                    "hidden layer and a single linear output, minimizing MSE. Given input x, "
                    "target y, weights W1/b1 (hidden) and W2/b2 (output), and a learning rate, "
                    "perform one forward pass, compute the output gradient, backpropagate "
                    "through the hidden layer, and update all weights by gradient descent. "
                    "Return the updated (W1, b1, W2, b2)."
                ),
                "tags": {"primary": "backprop", "secondary": ["mlp", "gradient_descent_sgd"]},
                "max_score": 5,
                "difficulty": 4,
            },
            {
                "key": "adam_step",
                "prompt": (
                    "Implement one Adam update step. Given a gradient g and the first/second "
                    "moment accumulators m and v, update m = beta1*m + (1-beta1)*g, v = "
                    "beta2*v + (1-beta2)*g^2, apply bias correction (divide by 1 - beta^t), "
                    "and return the updated parameter, m, and v using param_new = param - lr "
                    "* m_hat / (sqrt(v_hat) + eps)."
                ),
                "tags": {"primary": "optimizers_adam", "secondary": ["lr_scheduling"]},
                "max_score": 5,
                "difficulty": 3,
            },
            {
                "key": "lr_at_step",
                "prompt": (
                    "Implement a cosine annealing learning-rate schedule with linear warm-up. "
                    "Given the current step t, total steps T, warm-up steps W, and "
                    "initial/final learning rates, return the learning rate at step t: linear "
                    "ramp up to lr_init during warm-up (if t < W), then cosine decay from "
                    "lr_init down to lr_final over the remaining steps."
                ),
                "tags": {"primary": "lr_scheduling", "secondary": ["gradient_descent_sgd"]},
                "max_score": 5,
                "difficulty": 2,
            },
        ],
        "difficulty": 4,
        "max_score": 15,
        "task_type": "implement",
        "context_notes": (
            "Training a neural network repeatedly applies the same loop: backpropagation "
            "computes the gradient of the loss with respect to every weight by the chain "
            "rule, an optimizer moves the weights downhill, and a learning-rate schedule "
            "controls the step size over time. Adam keeps momentum and a running mean of "
            "squared gradients with bias correction. Cosine annealing with warm-up starts "
            "small to avoid destabilizing early gradients, then decays smoothly."
        ),
    },
    {
        "slug": "regression_fit",
        "prompt": (
            "Implement regression fitting: closed-form ordinary least squares for a simple "
            "linear model, and a ridge (L2-regularized) version trained by gradient descent."
        ),
        "scaffold": (
            "def fit_linear(x: list[float], y: list[float]) -> tuple[float, float, float]:\n"
            "    # TODO: return (slope, intercept, r_squared)\n"
            "    pass\n\n\n"
            "import numpy as np\n\n\n"
            "def ridge_gd(X: np.ndarray, y: np.ndarray, lam: float = 0.1, lr: float = 0.01, steps: int = 200) -> np.ndarray:\n"
            "    # TODO: return weight vector\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "fit_linear",
                "prompt": (
                    "Implement ordinary least squares linear regression with closed-form "
                    "equations. Given lists of x and y, return (slope, intercept, r_squared). "
                    "Handle a constant x (zero variance) by returning slope 0.0 and intercept "
                    "equal to the mean of y. R^2 = 1 - SS_res/SS_tot."
                ),
                "tags": {"primary": "linear_regression", "secondary": ["bias_variance", "regression_metrics"]},
                "max_score": 5,
                "difficulty": 2,
            },
            {
                "key": "ridge_gd",
                "prompt": (
                    "Implement ridge (L2-regularized) linear regression trained by gradient "
                    "descent. Given a numpy feature matrix X (with an added bias column of "
                    "ones) and target vector y, run T steps of gradient descent on MSE + lam * "
                    "sum(w^2) with a fixed learning rate, and return the weight vector. "
                    "Initialize weights to zeros."
                ),
                "tags": {"primary": "regularization", "secondary": ["gradient_descent_sgd"]},
                "max_score": 5,
                "difficulty": 3,
            },
        ],
        "difficulty": 3,
        "max_score": 10,
        "task_type": "apply",
        "context_notes": (
            "Linear regression models y as a linear function of x; the closed-form least-squares "
            "solution minimizes mean squared error and R^2 measures the fraction of variance "
            "explained. Regularization adds a penalty on weight magnitude to the loss, keeping "
            "the model simple and guarding against overfitting. Gradient descent minimizes the "
            "regularized objective directly when features are high-dimensional."
        ),
    },
    {
        "slug": "regression_fit_ridge",
        "depends_on": "regression_fit",
        "prompt": (
            "Extend the regression code you wrote to guard against overfitting. Add an "
            "``overfit_check`` helper that fits the plain (unregularized) closed-form model "
            "on the first (1 - test_frac) fraction of the data, computes train MSE and "
            "held-out test MSE, and returns both — a large gap signals overfitting. Then "
            "modify the ridge fit so that when ``lam > 0`` the returned weights shrink "
            "toward zero versus the plain fit."
        ),
        "scaffold": (
            "def fit_linear(x: list[float], y: list[float]) -> tuple[float, float, float]:\n"
            "    # TODO: return (slope, intercept, r_squared)\n"
            "    pass\n\n\n"
            "def overfit_check(x: list[float], y: list[float], test_frac: float = 0.3) -> tuple[float, float]:\n"
            "    # TODO: return (train_mse, test_mse)\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "tags": {"primary": "overfitting_underfitting", "secondary": ["data_leakage_calibration"]},
        "task_type": "apply",
        "context_notes": (
            "Overfitting is when a model memorizes training data and fails on new data, "
            "showing a big train/test gap. Evaluating on a held-out test set the model never "
            "saw is the only honest measure of generalization, and ridge regularization "
            "shrinks weights to keep the model simple. This version extends your earlier "
            "regression fit with exactly those checks."
        ),
    },
    {
        "slug": "model_selection",
        "prompt": (
            "Implement model-selection plumbing: stratified k-fold cross-validation splits "
            "and a grid search over candidate learning rates."
        ),
        "scaffold": (
            "import random\n\n\n"
            "def stratified_kfold_splits(labels: list[int], k: int = 5, seed: int = 0) -> list[tuple[list[int], list[int]]]:\n"
            "    # TODO: return k (train_indices, test_indices) splits preserving class proportions\n"
            "    pass\n\n\n"
            "def grid_search(candidates: list[float], train_fn, validate_fn) -> tuple[float, float]:\n"
            "    # TODO: return (best_candidate, best_score)\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "stratified_kfold_splits",
                "prompt": (
                    "Implement k-fold cross-validation splits that preserve class proportions. "
                    "Given a list of binary labels, produce k lists of (train_indices, "
                    "test_indices) such that each test fold contains approximately the same "
                    "fraction of each class as the full dataset. Shuffle indices with a fixed "
                    "seed before splitting. Return a list of k (train_indices, test_indices) "
                    "tuples as lists of ints."
                ),
                "tags": {"primary": "cross_validation", "secondary": ["pandas_cleaning", "bias_variance"]},
                "max_score": 5,
                "difficulty": 3,
            },
            {
                "key": "grid_search",
                "prompt": (
                    "Implement a grid search over candidate learning rates. Given a list of "
                    "candidates, a train_fn(candidate) -> model, and a validate_fn(model) -> "
                    "score, train a model for each candidate, score it on validation, and "
                    "return (best_candidate, best_score). Keep the first candidate on ties. "
                    "Higher scores are better."
                ),
                "tags": {"primary": "hyperparameter_tuning", "secondary": ["cross_validation"]},
                "max_score": 5,
                "difficulty": 2,
            },
        ],
        "difficulty": 3,
        "max_score": 10,
        "task_type": "apply",
        "context_notes": (
            "Cross-validation estimates generalization by rotating which part of the data is "
            "held out; stratification keeps class proportions constant across folds. "
            "Hyperparameters control the learning process itself and are not learned from "
            "data, so grid search tries every candidate on a validation set. The two pair "
            "naturally: an honest split plus a small search budget."
        ),
    },
    {
        "slug": "classifier_prep",
        "prompt": (
            "Implement classifier preprocessing: class-weighted oversampling to balance an "
            "imbalanced dataset, and distance-weighted k-nearest-neighbors prediction."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def balance_by_oversampling(X: np.ndarray, y: np.ndarray, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:\n"
            "    # TODO: return (X_balanced, y_balanced)\n"
            "    pass\n\n\n"
            "def knn_predict(train: list[tuple[tuple[float, float], int]], point: tuple[float, float], k: int = 3) -> int:\n"
            "    # TODO: return predicted label\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "balance_by_oversampling",
                "prompt": (
                    "Implement class-weighted oversampling. Given a numpy feature matrix X and "
                    "binary labels y, return a new dataset (X_balanced, y_balanced) where the "
                    "minority class is duplicated by random resampling with replacement so "
                    "both classes have the same number of rows. Use a fixed seed."
                ),
                "tags": {"primary": "imbalanced_classes", "secondary": ["classification_logistic"]},
                "max_score": 5,
                "difficulty": 2,
            },
            {
                "key": "knn_predict",
                "prompt": (
                    "Implement k-nearest-neighbors prediction with distance-weighted voting. "
                    "Given a list of training points as ((x, y), label) tuples and a new query "
                    "point, find the k nearest neighbors and predict the label by weighting "
                    "each neighbor's vote by 1/distance. If a neighbor has distance 0, return "
                    "its label immediately. Break ties toward the lower label."
                ),
                "tags": {"primary": "knn_svm_naivebayes", "secondary": ["scaling_encoding"]},
                "max_score": 5,
                "difficulty": 2,
            },
        ],
        "difficulty": 2,
        "max_score": 10,
        "task_type": "apply",
        "context_notes": (
            "Imbalanced datasets bias classifiers toward the majority class; oversampling "
            "duplicates minority examples so both classes have equal weight. K-nearest-"
            "neighbors classifies by the labels of nearby points, with distance-weighted "
            "voting giving closer neighbors more influence. Both are simple, effective "
            "preprocessing/baseline techniques that pair well together."
        ),
    },
    {
        "slug": "dim_reduction",
        "prompt": (
            "Implement dimensionality reduction: PCA via the SVD of the centered data matrix, "
            "and Lloyd's K-Means clustering for a 2D dataset."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def pca(X: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:\n"
            "    # TODO: return (components shape (k, d), explained_variance_ratio shape (k,))\n"
            "    pass\n\n\n"
            "import random\n\n\n"
            "def kmeans(points: list[tuple[float, float]], k: int, seed: int = 0, max_iter: int = 100) -> tuple[list[tuple[float, float]], float]:\n"
            "    # TODO: return (centroids, total_within_ss)\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "pca",
                "prompt": (
                    "Implement PCA via the SVD of the centered data matrix. Given an n-by-d "
                    "numpy matrix, subtract the column mean from each row, compute the SVD, "
                    "and return the top-k principal components (right singular vectors) and "
                    "the fraction of total variance each explains (squared singular values "
                    "normalized by the sum). Return (components, explained_variance_ratio)."
                ),
                "tags": {"primary": "dimensionality_reduction", "secondary": ["scaling_encoding", "pandas_cleaning"]},
                "max_score": 5,
                "difficulty": 3,
            },
            {
                "key": "kmeans",
                "prompt": (
                    "Implement Lloyd's K-Means clustering for a 2D dataset. Given a list of "
                    "(x, y) points and k, initialize centroids from k distinct seeded-random "
                    "points, then alternate between assigning each point to its nearest "
                    "centroid and recomputing centroids as cluster means until centroids stop "
                    "changing or max_iter is reached. Return the final centroids and the "
                    "total within-cluster sum of squared distances."
                ),
                "tags": {"primary": "clustering_kmeans", "secondary": ["pandas_cleaning", "metrics_classification"]},
                "max_score": 5,
                "difficulty": 3,
            },
        ],
        "difficulty": 3,
        "max_score": 10,
        "task_type": "apply",
        "context_notes": (
            "PCA finds the directions of greatest variance by taking the SVD of the "
            "mean-centered data; the right singular vectors are the components and their "
            "squared singular values give variance explained. K-Means partitions points by "
            "alternating assignment and centroid recomputation, converging to a local "
            "optimum. Both reduce/compress the data so downstream classifiers are simpler "
            "and faster."
        ),
    },
    {
        "slug": "tree_interpretability",
        "prompt": (
            "Implement decision-tree internals and model explanation: the Gini-impurity "
            "split-finding step of a decision tree, and permutation feature importance."
        ),
        "scaffold": (
            "def best_gini_split(features: list[float], labels: list[int]) -> tuple[float | None, float]:\n"
            "    # TODO: return (best_threshold, best_weighted_gini)\n"
            "    pass\n\n\n"
            "import numpy as np\n\n\n"
            "def permutation_importance(X: np.ndarray, y: np.ndarray, predict, metric, seed: int = 0) -> list[float]:\n"
            "    # TODO: return importance per feature column\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "best_gini_split",
                "prompt": (
                    "Implement the split-finding step of a decision tree. Given a list of "
                    "feature values and binary labels, evaluate every midpoint between "
                    "consecutive sorted unique feature values as a threshold and return the "
                    "(threshold, weighted_gini_impurity) pair with the lowest weighted Gini "
                    "impurity. Gini(node) = 1 - sum(p^2) over class proportions. If no valid "
                    "threshold exists, return (None, 1.0)."
                ),
                "tags": {"primary": "trees_ensembles", "secondary": ["feature_construction"]},
                "max_score": 5,
                "difficulty": 3,
            },
            {
                "key": "permutation_importance",
                "prompt": (
                    "Implement permutation feature importance. Given a feature matrix X, "
                    "labels y, a predictor (callable returning predictions), and a metric "
                    "(callable on y_true, y_pred, higher is better), compute the baseline "
                    "score, then for each feature column shuffle that column's values (fixed "
                    "seed) and record the score drop = baseline - shuffled_score. Return a "
                    "list of importance scores, one per column."
                ),
                "tags": {"primary": "explainability", "secondary": ["reproducibility_tracking"]},
                "max_score": 5,
                "difficulty": 3,
            },
        ],
        "difficulty": 3,
        "max_score": 10,
        "task_type": "apply",
        "context_notes": (
            "Decision trees recursively split the data to separate classes, choosing the "
            "split that most reduces Gini impurity. Explainability asks why a model made "
            "its predictions: permutation importance measures the performance drop when a "
            "feature's values are shuffled, so a large drop means the feature matters. "
            "Shuffling with a fixed seed makes the measurement reproducible."
        ),
    },
    {
        "slug": "generalization_monitoring",
        "prompt": (
            "Implement generalization monitoring: a z-score anomaly detector and a "
            "population-stability/KS drift score between two binned score distributions."
        ),
        "scaffold": (
            "def zscore_anomalies(values: list[float], threshold: float = 3.0) -> list[int]:\n"
            "    # TODO: return list of anomaly indices\n"
            "    pass\n\n\n"
            "import math\n\n\n"
            "def drift_scores(expected_props: list[float], observed_props: list[float], eps: float = 1e-6) -> tuple[float, float]:\n"
            "    # TODO: return (psi, ks_stat)\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "drift_scores",
                "prompt": (
                    "Implement the population stability index (PSI) and a KS-style drift score "
                    "between two binned score distributions. Given expected and observed "
                    "bucket proportions (each a list of floats summing to ~1), compute PSI = "
                    "sum((obs - exp) * ln(obs / exp)) and the KS statistic = max absolute "
                    "difference of the cumulative distributions. Use a small epsilon (1e-6) "
                    "for zero counts. Return (psi, ks)."
                ),
                "tags": {"primary": "monitoring_drift", "secondary": ["metrics_classification"]},
                "max_score": 5,
                "difficulty": 3,
            },
            {
                "key": "zscore_anomalies",
                "prompt": (
                    "Implement a z-score anomaly detector. Given a list of values, compute the "
                    "mean and sample standard deviation, then return the indices of values "
                    "whose absolute z-score exceeds a threshold (default 3.0). Handle constant "
                    "data (zero standard deviation) by flagging no anomalies."
                ),
                "tags": {"primary": "missing_outliers", "secondary": ["distributions"]},
                "max_score": 5,
                "difficulty": 1,
            },
        ],
        "difficulty": 3,
        "max_score": 10,
        "task_type": "apply",
        "context_notes": (
            "Model monitoring watches for drift: when the distribution of model inputs or "
            "outputs changes from training, PSI and the KS statistic are early-warning "
            "signals. Outliers are extreme values that can skew statistics; a z-score "
            "measures how many standard deviations a value is from the mean, so large "
            "absolute z-scores flag anomalies. Both are data-quality/monitoring "
            "prerequisites before trusting a deployed model."
        ),
    },
    {
        "slug": "stats_inference",
        "prompt": (
            "Implement statistical inference: a bootstrap confidence interval and a "
            "one-sample t-test with a two-sided p-value."
        ),
        "scaffold": (
            "import random\n\n\n"
            "def bootstrap_ci(data: list[float], statistic, b: int = 1000, seed: int = 0) -> tuple[float, float]:\n"
            "    # TODO: return (ci_low, ci_high)\n"
            "    pass\n\n\n"
            "import math\n\n\n"
            "def ttest(sample: list[float], mu0: float = 0.0) -> tuple[float, float]:\n"
            "    # TODO: return (t_stat, p_value)\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "bootstrap_ci",
                "prompt": (
                    "Implement a bootstrap confidence interval. Given a list of sample values "
                    "and a statistic function, draw B bootstrap resamples with replacement, "
                    "compute the statistic on each, and return the 2.5th and 97.5th "
                    "percentiles of the resampled statistics as the 95% CI. Use a fixed seed "
                    "so results are reproducible."
                ),
                "tags": {"primary": "bootstrap_ci", "secondary": ["missing_outliers"]},
                "max_score": 5,
                "difficulty": 3,
            },
            {
                "key": "ttest",
                "prompt": (
                    "Implement a one-sample t-test and return the t statistic and a two-sided "
                    "p-value. Given a sample and a hypothesized mean mu0, compute t = (mean - "
                    "mu0) / (std / sqrt(n)) using the sample standard deviation with n-1 "
                    "degrees of freedom. Compute the two-sided p-value with the normal "
                    "approximation via the error function: p = erfc(|t| / sqrt(2)). Do not "
                    "import scipy. Return (t, p)."
                ),
                "tags": {"primary": "hypothesis_pvalue", "secondary": ["bayes_mle", "distributions"]},
                "max_score": 5,
                "difficulty": 3,
            },
        ],
        "difficulty": 3,
        "max_score": 10,
        "task_type": "apply",
        "context_notes": (
            "The bootstrap estimates the sampling distribution of a statistic by resampling "
            "with replacement, giving a confidence interval without parametric assumptions. "
            "Hypothesis testing asks whether an observed effect is larger than chance: the "
            "t-statistic standardizes the sample mean's deviation by its standard error, and "
            "the p-value is how extreme that would be under the null. Small p-values reject "
            "the null."
        ),
    },
    {
        "slug": "llm_lifecycle",
        "prompt": (
            "Implement pieces of the LLM lifecycle: subword tokenization via byte-pair "
            "encoding, lexical retrieval for RAG, a frozen-backbone fine-tuning head update, "
            "and symmetric int8 quantization with dequantization."
        ),
        "scaffold": (
            "def bpe_merge(corpus: list[list[int]]) -> tuple[tuple[int, int], list[list[int]]]:\n"
            "    # TODO: return (most_frequent_pair, corpus_with_pair_merged)\n"
            "    pass\n\n\n"
            "def retrieve(query: str, docs: list[str], k: int = 3) -> list[int]:\n"
            "    # TODO: return top-k doc indices by lexical overlap score\n"
            "    pass\n\n\n"
            "import numpy as np\n\n\n"
            "def finetune_head(features: np.ndarray, y_onehot: np.ndarray, W: np.ndarray, lr: float = 0.1) -> np.ndarray:\n"
            "    # TODO: return updated W (backbone is frozen)\n"
            "    pass\n\n\n"
            "def quantize_int8(values: list[float]) -> tuple[list[int], float]:\n"
            "    # TODO: return (int8 values, scale)\n"
            "    pass\n\n\n"
            "def dequantize_int8(qvalues: list[int], scale: float) -> list[float]:\n"
            "    # TODO: return recovered floats\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "bpe_merge",
                "prompt": (
                    "Implement the core of byte-pair encoding: count adjacent token-pair "
                    "frequencies across a tokenized corpus (a list of lists of ints), find "
                    "the most frequent pair, and return it along with a new corpus where "
                    "every occurrence of that pair is merged into a single new token id (the "
                    "current max token id + 1). Break frequency ties by the lexicographically "
                    "smaller pair."
                ),
                "tags": {"primary": "tokenization_bpe", "secondary": ["data_structures"]},
                "max_score": 5,
                "difficulty": 3,
            },
            {
                "key": "retrieve",
                "prompt": (
                    "Implement minimal lexical retrieval: given a query string and a list of "
                    "documents, score each document by the number of shared unique terms "
                    "normalized by the geometric mean of the number of unique terms in the "
                    "query and the document (a bag-of-words cosine proxy). Return the indices "
                    "of the top-k documents, ranked highest first. Tokenize by splitting on "
                    "whitespace and lowercasing."
                ),
                "tags": {"primary": "rag_retrieval", "secondary": ["pandas_cleaning"]},
                "max_score": 5,
                "difficulty": 2,
            },
            {
                "key": "finetune_head",
                "prompt": (
                    "Implement the gradient update for fine-tuning a classifier head while the "
                    "backbone is frozen. Given fixed backbone feature vectors (a numpy "
                    "matrix), one-hot labels, and a trainable head weight matrix W, take one "
                    "gradient descent step on the softmax cross-entropy loss over logits = "
                    "features @ W. Only W is updated (the backbone is frozen). Return the "
                    "updated W."
                ),
                "tags": {"primary": "pretraining_finetuning", "secondary": ["loss_functions"]},
                "max_score": 5,
                "difficulty": 3,
            },
            {
                "key": "quantize_int8",
                "prompt": (
                    "Implement symmetric int8 quantization. Given a list of floats, compute "
                    "scale = max(abs(x)) / 127, quantize each value to round(value / scale) "
                    "clamped to [-127, 127], and return (quantized, scale). Guard against "
                    "all-zero input by using scale = 1.0."
                ),
                "tags": {"primary": "quantization", "secondary": ["deployment_serving"]},
                "max_score": 5,
                "difficulty": 2,
            },
            {
                "key": "dequantize_int8",
                "prompt": (
                    "Implement dequantize_int8(qvalues, scale) that recovers approximate "
                    "floats from int8 values by multiplying back by the scale factor."
                ),
                "tags": {"primary": "quantization", "secondary": ["deployment_serving"]},
                "max_score": 5,
                "difficulty": 2,
            },
        ],
        "difficulty": 3,
        "max_score": 25,
        "task_type": "implement",
        "context_notes": (
            "The LLM lifecycle spans tokenization (byte-pair encoding merges the most "
            "frequent adjacent token pairs into subwords), retrieval-augmented generation "
            "(finding the most relevant documents for a query), fine-tuning (adapting a "
            "pretrained model to a task, often by training only a new classification head), "
            "and serving optimizations (int8 quantization shrinks models and speeds up "
            "inference). Each piece is a small, self-contained function."
        ),
    },
    {
        "slug": "deep_architectures",
        "prompt": (
            "Implement deep-architecture primitives: a 2D convolution for a single input "
            "channel and a single kernel, and one LSTM cell forward pass."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def conv2d_single(x: np.ndarray, kernel: np.ndarray, padding: int = 0, stride: int = 1) -> np.ndarray:\n"
            "    # TODO: return output matrix\n"
            "    pass\n\n\n"
            "def sigmoid(z):\n"
            "    return 1.0 / (1.0 + np.exp(-z))\n\n\n"
            "def lstm_cell(x: np.ndarray, h_prev: np.ndarray, c_prev: np.ndarray, W: np.ndarray, U: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:\n"
            "    # TODO: return (h_new, c_new)\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "conv2d_single",
                "prompt": (
                    "Implement a 2D convolution for a single input channel and a single "
                    "kernel with padding and stride. Given an input matrix and a kernel "
                    "matrix, apply zero padding, slide the kernel by stride, and return the "
                    "output matrix of the correct size: out = (in + 2*pad - k) // stride + 1. "
                    "Return a numpy array."
                ),
                "tags": {"primary": "cnn", "secondary": ["activation_normalization"]},
                "max_score": 5,
                "difficulty": 3,
            },
            {
                "key": "lstm_cell",
                "prompt": (
                    "Implement one LSTM cell forward pass. Given input x, previous hidden "
                    "state h_prev, previous cell state c_prev, and combined weight matrices "
                    "W (input), U (recurrent) and bias b, compute the four gates (input, "
                    "forget, cell candidate, output) from W@x + U@h_prev + b. Use sigmoid "
                    "for the input/forget/output gates and tanh for the candidate. Update "
                    "c = f*c_prev + i*cand, h = o*tanh(c). Return (h, c)."
                ),
                "tags": {"primary": "rnn_lstm", "secondary": ["activation_normalization"]},
                "max_score": 5,
                "difficulty": 4,
            },
        ],
        "difficulty": 4,
        "max_score": 10,
        "task_type": "implement",
        "context_notes": (
            "Convolutional layers slide a small kernel over the input to detect patterns "
            "regardless of position, with padding preserving spatial size and stride "
            "controlling density. Recurrent networks carry state across time steps; an LSTM "
            "adds a cell state that gated operations can add to or erase, solving the "
            "vanishing-gradient problem of plain RNNs. These two primitives are the "
            "backbone of CNNs and sequence models."
        ),
    },
    {
        "slug": "data_pipeline",
        "prompt": (
            "Implement data-pipeline infrastructure: a small functional-style ETL pipeline "
            "and a bounded queue."
        ),
        "scaffold": (
            "from functools import reduce\n\n\n"
            "def etl_pipeline(rows: list[dict]) -> dict[str, float]:\n"
            "    # TODO: return {tag: total_amount}\n"
            "    pass\n\n\n"
            "import collections\n\n\n"
            "class BoundedQueue:\n"
            "    def __init__(self, capacity: int):\n"
            "        # TODO\n"
            "        ...\n\n"
            "    def put(self, item) -> bool:\n"
            "        # TODO: return True on success, False when full\n"
            "        ...\n\n"
            "    def get(self):\n"
            "        # TODO: return item, or None when empty\n"
            "        ...\n"
        ),
        "parts": [
            {
                "key": "etl_pipeline",
                "prompt": (
                    "Implement a small ETL pipeline in functional style. Given a list of raw "
                    "dict rows (keys 'name', 'amount', 'tag'), (1) filter out rows with "
                    "non-positive amounts, (2) map each surviving row to a (tag, amount) "
                    "pair, and (3) reduce the pairs into a dict mapping tag to total amount. "
                    "Use filter/map/reduce semantics only (no mutable accumulators or loops)."
                ),
                "tags": {"primary": "functional", "secondary": ["pandas_cleaning", "joins_merges"]},
                "max_score": 5,
                "difficulty": 2,
            },
            {
                "key": "BoundedQueue",
                "prompt": (
                    "Implement a plain bounded queue with a fixed capacity. Back it with a "
                    "collections.deque. put(item) appends at the back and returns True, or "
                    "returns False when the queue is full; get() pops from the front and "
                    "returns the item, or None when empty. This version is single-threaded."
                ),
                "tags": {"primary": "data_structures", "secondary": ["generators_iterators"]},
                "max_score": 5,
                "difficulty": 3,
            },
        ],
        "difficulty": 3,
        "max_score": 10,
        "task_type": "apply",
        "context_notes": (
            "Functional style expresses data pipelines as composed pure operations: filter, "
            "map, reduce — easy to test and reason about, and the core of ETL. A bounded "
            "queue synchronizes producers and consumers with a fixed capacity and is the "
            "basis of producer-consumer pipelines; this plain version is the single-threaded "
            "predecessor of a thread-safe one."
        ),
    },
    {
        "slug": "thread_queue_safe",
        "depends_on": "data_pipeline",
        "prompt": (
            "Make the bounded queue thread-safe. Extend your BoundedQueue so it uses a "
            "collections.deque, a threading.Lock, and two threading.Condition variables: "
            "put() blocks when full and get() blocks when empty. Both methods accept an "
            "optional timeout (seconds); put returns True on success and False on timeout, "
            "and get returns the item or None on timeout."
        ),
        "scaffold": (
            "import collections\n"
            "import threading\n\n\n"
            "class BoundedQueue:\n"
            "    def __init__(self, capacity: int):\n"
            "        # TODO\n"
            "        ...\n\n"
            "    def put(self, item, timeout: float | None = None) -> bool:\n"
            "        # TODO: return True on success, False on timeout\n"
            "        ...\n\n"
            "    def get(self, timeout: float | None = None):\n"
            "        # TODO: return item, or None on timeout\n"
            "        ...\n"
        ),
        "difficulty": 4,
        "max_score": 5,
        "tags": {"primary": "data_structures", "secondary": ["generators_iterators"]},
        "task_type": "implement",
        "context_notes": (
            "Thread-safety requires a lock around every mutation and condition variables to "
            "wake waiters when space or items appear. Blocking with timeout avoids deadlock "
            "when producers or consumers stall. This version extends the plain bounded "
            "queue you built in the data-pipeline block with real concurrency control."
        ),
    },
    {
        "slug": "eval_metrics",
        "prompt": (
            "Implement evaluation metrics: a confusion matrix with derived binary "
            "classification metrics, and a train/test gap that detects overfitting."
        ),
        "scaffold": (
            "def binary_metrics(y_true: list[int], y_pred: list[int]) -> dict:\n"
            "    # TODO: return {\"confusion\": [[tn, fp], [fn, tp]], \"accuracy\": ..., \"precision\": ..., \"recall\": ..., \"f1\": ...}\n"
            "    pass\n\n\n"
            "import numpy as np\n\n\n"
            "def train_test_gap(x: list[float], y: list[float], degree: int, test_frac: float = 0.3) -> tuple[float, float]:\n"
            "    # TODO: return (train_mse, test_mse)\n"
            "    pass\n"
        ),
        "parts": [
            {
                "key": "binary_metrics",
                "prompt": (
                    "Implement a confusion matrix and the derived metrics for a binary "
                    "classifier. Given lists of true labels and predicted labels (each 0/1), "
                    "return a dict with the 2x2 confusion matrix [[TN, FP], [FN, TP]] and "
                    "accuracy, precision, recall, and F1. Guard against division by zero by "
                    "returning 0.0 for undefined precision/recall/F1."
                ),
                "tags": {"primary": "metrics_classification", "secondary": ["classification_logistic"]},
                "max_score": 5,
                "difficulty": 2,
            },
            {
                "key": "train_test_gap",
                "prompt": (
                    "Implement an overfitting detector. Given x and y lists and a polynomial "
                    "degree, fit a least-squares polynomial on the first (1 - test_frac) "
                    "fraction of the data, then compute train MSE on the training portion and "
                    "test MSE on the held-out portion. Return (train_mse, test_mse). A large "
                    "gap between them signals overfitting."
                ),
                "tags": {"primary": "overfitting_underfitting", "secondary": ["data_leakage_calibration"]},
                "max_score": 5,
                "difficulty": 3,
            },
        ],
        "difficulty": 3,
        "max_score": 10,
        "task_type": "apply",
        "context_notes": (
            "Classification metrics summarize how well a model separates classes: the "
            "confusion matrix breaks predictions into true/false positives and negatives, "
            "from which precision, recall, and F1 derive. Overfitting shows up as a big "
            "train/test gap, so measuring the held-out error is the honest check on "
            "generalization. Data leakage — letting test information leak into training — "
            "inflates those estimates and is the hazard these metrics guard against."
        ),
    },
]


def _row_tuple(seed: dict[str, Any]) -> tuple:
    """Convert a catalog entry into an INSERT row tuple.

    Block rows carry ``parts_json``; version successors get
    ``depends_on_task_id``/``version_root_id`` (deterministic seed ids) and
    ``version_index = 2``.
    """
    parts = seed.get("parts") or []
    tags = _derive_tags(seed)
    difficulty = seed.get("difficulty") or (
        max(p["difficulty"] for p in parts) if parts else 2
    )
    max_score = seed.get("max_score") or (
        sum(p["max_score"] for p in parts) if parts else 5
    )
    depends = seed.get("depends_on")
    version_index = 2 if depends else 1
    root_slug = seed.get("version_root") or (depends or seed["slug"])
    return (
        f"seed_{seed['slug']}",
        SYSTEM_OWNER,
        seed["prompt"],
        seed.get("scaffold"),
        max(1, min(5, int(difficulty))),
        int(max_score),
        json.dumps(parts),
        (seed.get("context_notes") or "").strip()[:2000],
        json.dumps(tags),
        seed.get("task_type", "implement"),
        "seed",
        None,
        None,
        version_index,
        f"seed_{depends}" if depends else None,
        f"seed_{root_slug}",
        1,
        str(_utcnow_naive()),
    )


_TASK_COLUMNS = (
    "id", "owner", "prompt", "scaffold", "difficulty", "max_score",
    "parts_json", "context_notes", "tags_json", "task_type", "source",
    "parent_task_id", "target_text", "version_index", "depends_on_task_id",
    "version_root_id", "is_public", "created_at",
)


def seed_question_bank() -> int:
    """Idempotently insert the builtin catalog. Returns number inserted.

    Hermetic: no network, no model calls — ``context_notes`` are pre-authored.
    Single batched ``INSERT OR IGNORE`` (one transaction for the whole
    catalog) keyed on the primary key, so a human-edited seed row is never
    overwritten and re-runs are no-ops. After the insert, stale ``source='seed'``
    rows whose id is no longer in the catalog are deleted, so a catalog
    restructure needs no manual ``--reset``.
    """
    from coach.db import create_schema, sqlite_conn

    create_schema()
    rows = [_row_tuple(seed) for seed in SEED_CATALOG]
    if not rows:
        return 0
    placeholders = ", ".join(["?"] * len(_TASK_COLUMNS))
    values_clause = ", ".join([f"({placeholders})"] * len(rows))
    sql = (
        f"INSERT OR IGNORE INTO tasks ({', '.join(_TASK_COLUMNS)}) "
        f"VALUES {values_clause}"
    )
    params: list = [v for row in rows for v in row]
    catalog_ids = [f"seed_{seed['slug']}" for seed in SEED_CATALOG]
    with sqlite_conn() as conn:
        cur = conn.execute(sql, params)
        stale_placeholders = ", ".join(["?"] * len(catalog_ids))
        conn.execute(
            f"DELETE FROM tasks WHERE source = 'seed' "
            f"AND id NOT IN ({stale_placeholders})",
            catalog_ids,
        )
        conn.commit()
        return cur.rowcount


def _seed_rows() -> list[dict]:
    """Tasks in the DB that are seeds (source seed/seed_llm/seed_admin)."""
    from coach.db import create_schema, learner_session
    from coach.tasks import TaskModel, task_to_dict
    from sqlalchemy import select

    create_schema()
    session = learner_session()
    try:
        rows = session.scalars(
            select(TaskModel).where(TaskModel.source.in_(["seed", "seed_llm", "seed_admin"]))
        ).all()
        return [task_to_dict(m) for m in rows]
    finally:
        session.close()


def _all_task_tags(task: dict) -> list[str]:
    """Tags on a task: block tags + every part's tags (primary + secondary)."""
    tags = task.get("tags") or {}
    out = [tags.get("primary")] + list(tags.get("secondary") or [])
    for part in task.get("parts") or []:
        ptags = part.get("tags") or {}
        out += [ptags.get("primary")] + list(ptags.get("secondary") or [])
    return [t for t in out if t]


def _attempts_by_tag() -> dict[str, dict[str, int]]:
    """Per-tag/per-family -> {candidate: attempt_count} across all tasks.

    Derived from ``session_steps`` joined on the task's tags (primary or
    secondary, block or part level). Used by ``coverage_report`` for
    per-candidate asked counts.
    """
    from coach.db import create_schema, learner_session
    from coach.steps import SessionStepModel
    from coach.tasks import TaskModel, parse_parts, parse_tags
    from sqlalchemy import select

    create_schema()
    session = learner_session()
    try:
        tasks = session.execute(select(TaskModel.id, TaskModel.tags_json, TaskModel.parts_json)).all()
        attempts = session.execute(
            select(SessionStepModel.candidate, SessionStepModel.task_id)
        ).all()
        tag_map: dict[str, list[str]] = {}
        for task_id, tags_json, parts_json in tasks:
            tags = parse_tags(tags_json)
            parts = parse_parts(parts_json)
            tag_list = [tags.get("primary")] + list(tags.get("secondary") or [])
            for part in parts:
                ptags = part.get("tags") or {}
                tag_list += [ptags.get("primary")] + list(ptags.get("secondary") or [])
            # A task counts once per tag, even when several parts share one.
            tag_map[task_id] = list(dict.fromkeys(t for t in tag_list if t))
        out: dict[str, dict[str, int]] = {}
        for candidate, task_id in attempts:
            for tag in tag_map.get(task_id, []):
                fam = TAG_TO_FAMILY.get(tag) or (tag if tag in FAMILIES else None)
                for key in (tag, fam):
                    if key is None:
                        continue
                    per = out.setdefault(key, {})
                    per[candidate] = per.get(candidate, 0) + 1
        return out
    finally:
        session.close()


def coverage_report() -> dict:
    """Per-family and per-tag seed coverage + per-candidate asked counts.

    Returns::

        {
          "families": {fam: {"seed_tasks": [ids], "tags": [tag, ...],
                              "asked_total": n, "candidates": {email: n}}},
          "tags":     {tag: {"seed_tasks": [ids], "family": fam,
                              "asked_total": n, "candidates": {email: n}}},
        }

    A tag/family counts as covered if it appears as primary or secondary on
    any seed task (block-level or on any part).
    """
    from coach.taxonomy import TAGS as _TAGS

    seeds = _seed_rows()
    by_tag: dict[str, list[str]] = {tag: [] for tag in ALL_TAGS}
    by_family: dict[str, list[str]] = {fam: [] for fam in FAMILIES}
    for t in seeds:
        for tag in _all_task_tags(t):
            if tag in by_tag:
                by_tag[tag].append(t["id"])
            fam = TAG_TO_FAMILY.get(tag)
            if fam and fam in by_family:
                by_family[fam].append(t["id"])

    attempts = _attempts_by_tag()
    families = {}
    for fam in FAMILIES:
        fam_attempts = attempts.get(fam, {})
        families[fam] = {
            "seed_tasks": sorted(set(by_family[fam])),
            "tags": list(_TAGS.get(fam, [])),
            "asked_total": sum(fam_attempts.values()),
            "candidates": fam_attempts,
        }
    tags = {}
    for tag in ALL_TAGS:
        tag_attempts = attempts.get(tag, {})
        tags[tag] = {
            "seed_tasks": sorted(set(by_tag[tag])),
            "family": TAG_TO_FAMILY.get(tag),
            "asked_total": sum(tag_attempts.values()),
            "candidates": tag_attempts,
        }
    return {"families": families, "tags": tags}


def _fill_gaps(limit: int = 5) -> list[str]:
    """Mint tasks for the least-covered tags; returns the minted tags."""
    from coach.task_decomposer import TaskDecomposer
    from coach.tasks import create_task

    report = coverage_report()
    scored = sorted(
        report["tags"].items(),
        key=lambda kv: (len(kv[1]["seed_tasks"]), kv[0]),
    )
    zero_coverage = [tag for tag, info in scored if not info["seed_tasks"]]
    targets = zero_coverage[:limit] if zero_coverage else [tag for tag, _ in scored[:limit]]
    decomposer = TaskDecomposer()
    minted: list[str] = []
    for tag in targets:
        try:
            seed = decomposer.generate_seed_task_for_tag(tag, difficulty=2)
            tid = f"seed_llm_{tag}_{uuid.uuid4().hex[:6]}"
            create_task(
                prompt=seed["prompt"],
                owner=SYSTEM_OWNER,
                scaffold=seed.get("scaffold"),
                difficulty=seed.get("difficulty", 2),
                max_score=seed.get("max_score", 5),
                context_notes=seed.get("context_notes", ""),
                tags=seed["tags"],
                task_type=seed.get("task_type", "implement"),
                source="seed_llm",
                is_public=True,
                task_id=tid,
            )
            minted.append(tag)
            print(f"[fill-gaps] minted {tid} for tag={tag}")
        except Exception as exc:
            print(f"[fill-gaps] failed for tag={tag}: {exc}", file=sys.stderr)
    return minted


def main(argv: Optional[list[str]] = None) -> int:
    import os
    from pathlib import Path

    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except Exception:
        pass
    _ = os.getenv("GOOGLE_API_KEY")  # ensure .env is loaded before LLM paths

    parser = argparse.ArgumentParser(prog="coach.seed_bank")
    parser.add_argument(
        "--fill-gaps", action="store_true",
        help="Mint tasks for tags with zero/lowest seed coverage (LLM).",
    )
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Max number of gap tasks to mint (default 5).",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Wipe app data and re-bootstrap the question bank from SEED_CATALOG.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Confirm a destructive --reset (required; without it only a preview prints).",
    )
    args = parser.parse_args(argv)
    if args.reset:
        from coach.db import reset_database

        result = reset_database(preview=not args.yes)
        if result.get("preview"):
            wiped = result["wiped"]
            print("DRY RUN: reset would wipe these rows (users/auth preserved):")
            for table, count in sorted(wiped.items()):
                print(f"  {table:<20} {count}")
            print("Re-run with --reset --yes to perform the reset + reseed.")
            return 0
        print(
            f"Reset complete: deleted {result['total_deleted']} rows "
            f"({result['seeded']} seed tasks in sync)."
        )
        return 0
    if args.fill_gaps:
        minted = _fill_gaps(limit=args.limit)
        print(f"Filled gaps for {len(minted)} tags: {minted}")
        return 0
    inserted = seed_question_bank()
    print(f"Seeded {inserted} tasks (catalog size {len(SEED_CATALOG)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())