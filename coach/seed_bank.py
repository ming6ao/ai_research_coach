"""Builtin ML question bank + coverage reporting + gap-filling CLI.

Implements the design doc §3:

- ``SEED_CATALOG``: ~30 pre-authored, self-contained code tasks. Each task is
  a multi-tag exercise (1 primary + 0-2 secondary fine tags) so a small
  catalog covers every family and every fine tag. ``context_notes`` are
  pre-authored (no LLM/network at seed time).
- ``seed_question_bank()``: idempotent, hermetic, single-batched-transaction
  seeding (``INSERT OR IGNORE``) into the ``tasks`` table. A human-edited seed
  row is never overwritten; content fixes bump the slug.
- ``coverage_report()``: per-family/per-tag seed coverage (primary or
  secondary on any seed) + per-candidate asked counts.
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


# Each seed is: slug, prompt, scaffold, difficulty (1-5), max_score, hints,
# tags {primary, secondary}, task_type, context_notes (2-4 sentences),
# cluster (thematic thread id) and followups (list of {"task_id", "kind"}
# pointers to related seeds served as curated follow-ups after this task).
# Authoring rule (enforced by review, not code): every seed is self-contained,
# deterministic, and gradeable by the existing code judge.
SEED_CATALOG: list[dict[str, Any]] = [
    {
        "slug": "softmax",
        "cluster": "dl_architectures",
        "followups": [
            {"task_id": "seed_attention", "kind": "sibling"},
            {"task_id": "seed_finetune_head", "kind": "prereq"},
            {"task_id": "seed_lstm_cell", "kind": "sibling"},
        ],
        "prompt": (
            "Implement a numerically stable softmax and log_softmax for a list of logits. "
            "The softmax must subtract the max logit before exponentiating to avoid overflow, "
            "and the log_softmax must be computed directly (log of the normalized probability) "
            "so very negative inputs do not underflow. softmax must return probabilities that "
            "sum to 1.0 within floating point tolerance."
        ),
        "scaffold": (
            "def softmax(logits: list[float]) -> list[float]:\n"
            "    # TODO: numerically stable softmax\n"
            "    pass\n\n\n"
            "def log_softmax(logits: list[float]) -> list[float]:\n"
            "    # TODO: numerically stable log-softmax\n"
            "    pass\n"
        ),
        "difficulty": 2,
        "max_score": 5,
        "hints": [
            {
                "id": "softmax-max",
                "text": "Subtract max(logits) from every logit before exponentiating.",
                "weight": 0.15,
                "reveal_threshold": 0.55,
            },
            {
                "id": "softmax-sum",
                "text": "log_softmax(x) = x - max - log(sum(exp(x - max))).",
                "weight": 0.2,
                "reveal_threshold": 0.45,
            },
        ],
        "tags": {"primary": "activation_normalization", "secondary": ["loss_functions"]},
        "task_type": "implement",
        "context_notes": (
            "The softmax function converts raw logits into a probability distribution and is "
            "the final activation of a classification network. A numerically stable implementation "
            "subtracts the maximum logit before exponentiation so large inputs do not overflow. "
            "Log-softmax avoids the underflow that occurs when taking the log of a tiny probability "
            "directly. These two functions are also the core of the cross-entropy loss used to train classifiers."
        ),
    },
    {
        "slug": "kfold",
        "cluster": "eval_mlops",
        "followups": [
            {"task_id": "seed_grid_search", "kind": "sibling"},
            {"task_id": "seed_overfit_holdout", "kind": "sibling"},
            {"task_id": "seed_metrics_cm", "kind": "sibling"},
        ],
        "prompt": (
            "Implement k-fold cross-validation splits that preserve class proportions. Given a list "
            "of binary labels, produce k lists of (train_indices, test_indices) such that each test "
            "fold contains approximately the same fraction of each class as the full dataset. Shuffle "
            "indices with a fixed seed before splitting. Return a list of k (train_indices, test_indices) "
            "tuples as lists of ints."
        ),
        "scaffold": (
            "import random\n\n\n"
            "def stratified_kfold_splits(labels: list[int], k: int = 5, seed: int = 0) -> list[tuple[list[int], list[int]]]:\n"
            "    # TODO: return k (train_indices, test_indices) splits preserving class proportions\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "cross_validation", "secondary": ["pandas_cleaning", "bias_variance"]},
        "task_type": "apply",
        "context_notes": (
            "Cross-validation estimates how a model generalizes by training on part of the data and "
            "testing on the rest, rotating through folds. Stratification keeps each class's proportion "
            "constant across folds, which matters for imbalanced targets. More folds mean more training "
            "data but also correlated test sets, which is the bias-variance tradeoff in miniature. "
            "Cleaning and shuffling the data first is a prerequisite for honest splits."
        ),
    },
    {
        "slug": "linreg_r2",
        "cluster": "classical_ml",
        "followups": [
            {"task_id": "seed_ridge_l2", "kind": "sibling"},
            {"task_id": "seed_overfit_holdout", "kind": "sibling"},
            {"task_id": "seed_ttest_pvalue", "kind": "sibling"},
        ],
        "prompt": (
            "Implement ordinary least squares linear regression with closed-form equations. Given lists "
            "of x and y, return (slope, intercept, r_squared). Handle a constant x (zero variance) by "
            "returning slope 0.0 and intercept equal to the mean of y. R^2 = 1 - SS_res/SS_tot."
        ),
        "scaffold": (
            "def fit_linear(x: list[float], y: list[float]) -> tuple[float, float, float]:\n"
            "    # TODO: return (slope, intercept, r_squared)\n"
            "    pass\n"
        ),
        "difficulty": 2,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "linear_regression", "secondary": ["bias_variance", "regression_metrics"]},
        "task_type": "apply",
        "context_notes": (
            "Linear regression models y as a linear function of x and is the simplest supervised "
            "learning baseline. The closed-form least-squares solution minimizes mean squared error. "
            "R^2 measures the fraction of variance in y explained by the model, ranging from 1.0 "
            "(perfect) to negative values (worse than predicting the mean). Simple models like this "
            "illustrate the bias-variance tradeoff directly."
        ),
    },
    {
        "slug": "kmeans",
        "cluster": "classical_ml",
        "followups": [
            {"task_id": "seed_pca_svd", "kind": "sibling"},
            {"task_id": "seed_knn_weighted", "kind": "sibling"},
        ],
        "prompt": (
            "Implement Lloyd's K-Means clustering for a 2D dataset. Given a list of (x, y) points and "
            "k, initialize centroids from k distinct seeded-random points, then alternate between "
            "assigning each point to its nearest centroid and recomputing centroids as cluster means "
            "until centroids stop changing or max_iter is reached. Return the final centroids and the "
            "total within-cluster sum of squared distances."
        ),
        "scaffold": (
            "import random\n\n\n"
            "def kmeans(points: list[tuple[float, float]], k: int, seed: int = 0, max_iter: int = 100) -> tuple[list[tuple[float, float]], float]:\n"
            "    # TODO: return (centroids, total_within_ss)\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "clustering_kmeans", "secondary": ["pandas_cleaning", "metrics_classification"]},
        "task_type": "implement",
        "context_notes": (
            "K-Means is a partitional clustering algorithm that alternates between assigning points to "
            "the nearest centroid and recomputing centroids as cluster means. Lloyd's algorithm "
            "converges to a local optimum, so initialization matters. The within-cluster sum of squares "
            "decreases as k grows, and the elbow method uses the bend in that curve to choose k. When "
            "ground-truth labels exist, cluster quality is often summarized with classification metrics."
        ),
    },
    {
        "slug": "pca_svd",
        "cluster": "classical_ml",
        "followups": [
            {"task_id": "seed_knn_weighted", "kind": "sibling"},
            {"task_id": "seed_kmeans", "kind": "sibling"},
        ],
        "prompt": (
            "Implement PCA via the SVD of the centered data matrix. Given an n-by-d numpy matrix, "
            "subtract the column mean from each row, compute the SVD, and return the top-k principal "
            "components (right singular vectors) and the fraction of total variance each explains "
            "(squared singular values normalized by the sum). Return (components, explained_variance_ratio)."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def pca(X: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:\n"
            "    # TODO: return (components shape (k, d), explained_variance_ratio shape (k,))\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "dimensionality_reduction", "secondary": ["scaling_encoding", "pandas_cleaning"]},
        "task_type": "apply",
        "context_notes": (
            "PCA finds the directions of greatest variance in a dataset by taking the SVD of the "
            "mean-centered data. The right singular vectors are the principal components, and their "
            "squared singular values give the variance explained by each component. Centering is "
            "required before computing the SVD. Variance-explained ratios help choose the number of "
            "components and pair naturally with feature scaling."
        ),
    },
    {
        "slug": "backprop_mlp",
        "cluster": "dl_architectures",
        "followups": [
            {"task_id": "seed_adam", "kind": "sibling"},
            {"task_id": "seed_cosine_lr", "kind": "sibling"},
            {"task_id": "seed_conv2d", "kind": "sibling"},
            {"task_id": "seed_lstm_cell", "kind": "sibling"},
        ],
        "prompt": (
            "Implement one training step of backpropagation for a 2-layer MLP: a sigmoid hidden layer "
            "and a single linear output, minimizing MSE. Given input x, target y, weights W1/b1 (hidden) "
            "and W2/b2 (output), and a learning rate, perform one forward pass, compute the output "
            "gradient, backpropagate through the hidden layer, and update all weights by gradient "
            "descent. Return the updated (W1, b1, W2, b2)."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def bp_step(x: np.ndarray, y: float, W1: np.ndarray, b1: np.ndarray, W2: np.ndarray, b2: np.ndarray, lr: float = 0.1) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:\n"
            "    # TODO: return updated (W1, b1, W2, b2)\n"
            "    pass\n"
        ),
        "difficulty": 4,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "backprop", "secondary": ["mlp", "gradient_descent_sgd"]},
        "task_type": "implement",
        "context_notes": (
            "Backpropagation computes the gradient of the loss with respect to every weight by applying "
            "the chain rule backward through the network. It is the core training algorithm for neural "
            "networks, and every optimizer is a smarter way to use those gradients. A multilayer "
            "perceptron stacks affine layers with nonlinear activations so it can learn nonlinear "
            "functions. Gradient descent then moves the weights downhill along the computed gradients."
        ),
    },
    {
        "slug": "attention",
        "cluster": "dl_architectures",
        "followups": [
            {"task_id": "seed_kv_cache", "kind": "sibling"},
            {"task_id": "seed_softmax", "kind": "prereq"},
            {"task_id": "seed_bpe", "kind": "sibling"},
        ],
        "prompt": (
            "Implement a single scaled dot-product attention head. Given query, key, value matrices "
            "each of shape (n, d) and an optional boolean mask of shape (n, n), compute scores = "
            "Q @ K.T / sqrt(d), set masked positions to a very negative number, softmax over the last "
            "axis, and return the context vectors = attention @ V of shape (n, d)."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def attention(q: np.ndarray, k: np.ndarray, v: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:\n"
            "    # TODO: return context vectors shape (n, d)\n"
            "    pass\n"
        ),
        "difficulty": 4,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "attention_transformer", "secondary": ["kv_cache"]},
        "task_type": "implement",
        "context_notes": (
            "Scaled dot-product attention is the core mechanism of transformer models: each token "
            "attends to every other token weighted by how related their queries and keys are. The "
            "sqrt(d) scaling keeps dot products from growing with the dimension, which stabilizes the "
            "softmax. Masking prevents tokens from attending to future positions or padding. Because "
            "each query only needs the keys and values, caching them across decoding steps is natural."
        ),
    },
    {
        "slug": "rag_retrieval",
        "cluster": "llm_stack",
        "followups": [
            {"task_id": "seed_finetune_head", "kind": "sibling"},
            {"task_id": "seed_metrics_cm", "kind": "sibling"},
        ],
        "prompt": (
            "Implement minimal lexical retrieval: given a query string and a list of documents, score "
            "each document by the number of shared unique terms normalized by the geometric mean of the "
            "number of unique terms in the query and the document (a bag-of-words cosine proxy). Return "
            "the indices of the top-k documents, ranked highest first. Tokenize by splitting on "
            "whitespace and lowercasing."
        ),
        "scaffold": (
            "def retrieve(query: str, docs: list[str], k: int = 3) -> list[int]:\n"
            "    # TODO: return top-k doc indices by lexical overlap score\n"
            "    pass\n"
        ),
        "difficulty": 2,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "rag_retrieval", "secondary": ["pandas_cleaning"]},
        "task_type": "apply",
        "context_notes": (
            "Retrieval-augmented generation (RAG) first finds the most relevant documents for a query "
            "and then feeds them to a language model. A simple lexical scorer counts shared terms "
            "between the query and each document, approximating cosine similarity over bag-of-words "
            "vectors. The retrieved context must be relevant because the model answers only from what "
            "it sees. Cleaning the corpus first (lowercasing, tokenizing) is a data-engineering prerequisite."
        ),
    },
    {
        "slug": "kv_cache",
        "cluster": "llm_stack",
        "followups": [
            {"task_id": "seed_attention", "kind": "prereq"},
            {"task_id": "seed_quantize_int8", "kind": "sibling"},
        ],
        "prompt": (
            "Implement incremental attention decoding with a key/value cache. Given a new query token "
            "q, the new key k_new and value v_new, and the cached keys/values for prior tokens (or "
            "None on the first step), append the new key and value to the cache, then compute the "
            "scaled dot-product attention of the single new query over all cached tokens (including "
            "the new one). Return (context_vector, k_cache, v_cache)."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def decode_step(q: np.ndarray, k_new: np.ndarray, v_new: np.ndarray, k_cache: np.ndarray | None, v_cache: np.ndarray | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:\n"
            "    # TODO: return (context, k_cache, v_cache)\n"
            "    pass\n"
        ),
        "difficulty": 4,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "kv_cache", "secondary": ["attention_transformer"]},
        "task_type": "implement",
        "context_notes": (
            "Autoregressive generation processes one token at a time, and each new token must attend "
            "to all prior tokens. Without a cache, every step recomputes the keys and values of every "
            "past token, which is quadratic in sequence length. A key/value cache stores the already "
            "computed K and V so each step only computes the new token's key and value. This makes "
            "decoding linear in the number of steps and is a core LLM serving technique."
        ),
    },
    {
        "slug": "metrics_cm",
        "cluster": "eval_mlops",
        "followups": [
            {"task_id": "seed_overfit_holdout", "kind": "sibling"},
            {"task_id": "seed_drift_psi", "kind": "sibling"},
            {"task_id": "seed_oversample", "kind": "prereq"},
        ],
        "prompt": (
            "Implement a confusion matrix and the derived metrics for a binary classifier. Given lists "
            "of true labels and predicted labels (each 0/1), return a dict with the 2x2 confusion "
            "matrix [[TN, FP], [FN, TP]] and accuracy, precision, recall, and F1. Guard against "
            "division by zero by returning 0.0 for undefined precision/recall/F1."
        ),
        "scaffold": (
            "def binary_metrics(y_true: list[int], y_pred: list[int]) -> dict:\n"
            "    # TODO: return {\"confusion\": [[tn, fp], [fn, tp]], \"accuracy\": ..., \"precision\": ..., \"recall\": ..., \"f1\": ...}\n"
            "    pass\n"
        ),
        "difficulty": 2,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "metrics_classification", "secondary": ["classification_logistic"]},
        "task_type": "apply",
        "context_notes": (
            "Classification metrics summarize how well a model separates classes. The confusion matrix "
            "breaks predictions into true/false positives and negatives, from which precision, recall, "
            "and F1 are derived. Precision is how many positive predictions were right; recall is how "
            "many real positives were found; F1 is their harmonic mean. Accuracy alone can mislead on "
            "imbalanced classes, which is why these derived metrics matter."
        ),
    },
    {
        "slug": "bootstrap_ci",
        "cluster": "stats_inference",
        "followups": [
            {"task_id": "seed_ttest_pvalue", "kind": "sibling"},
            {"task_id": "seed_zscore_anomaly", "kind": "sibling"},
        ],
        "prompt": (
            "Implement a bootstrap confidence interval. Given a list of sample values and a statistic "
            "function, draw B bootstrap resamples with replacement, compute the statistic on each, and "
            "return the 2.5th and 97.5th percentiles of the resampled statistics as the 95% CI. Use a "
            "fixed seed so results are reproducible."
        ),
        "scaffold": (
            "import random\n\n\n"
            "def bootstrap_ci(data: list[float], statistic, b: int = 1000, seed: int = 0) -> tuple[float, float]:\n"
            "    # TODO: return (ci_low, ci_high)\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "bootstrap_ci", "secondary": ["missing_outliers"]},
        "task_type": "apply",
        "context_notes": (
            "The bootstrap estimates the sampling distribution of a statistic by resampling the "
            "observed data with replacement many times. It avoids parametric assumptions and works for "
            "nearly any statistic (mean, median, correlation). The percentiles of the resampled "
            "statistics give a confidence interval. Bootstrap intervals are robust to outliers when the "
            "statistic itself is robust."
        ),
    },
    {
        "slug": "oversample",
        "cluster": "classical_ml",
        "followups": [
            {"task_id": "seed_knn_weighted", "kind": "sibling"},
            {"task_id": "seed_metrics_cm", "kind": "sibling"},
        ],
        "prompt": (
            "Implement class-weighted oversampling. Given a numpy feature matrix X and binary labels y, "
            "return a new dataset (X_balanced, y_balanced) where the minority class is duplicated by "
            "random resampling with replacement so both classes have the same number of rows. Use a "
            "fixed seed."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def balance_by_oversampling(X: np.ndarray, y: np.ndarray, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:\n"
            "    # TODO: return (X_balanced, y_balanced)\n"
            "    pass\n"
        ),
        "difficulty": 2,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "imbalanced_classes", "secondary": ["classification_logistic"]},
        "task_type": "apply",
        "context_notes": (
            "Imbalanced datasets have far more of one class than the other, which biases classifiers "
            "toward the majority class. Oversampling duplicates minority examples to balance the "
            "training set without discarding data. It is a simple, effective preprocessing step before "
            "fitting a classifier. Random duplication with a fixed seed keeps experiments reproducible."
        ),
    },
    {
        "slug": "zscore_anomaly",
        "cluster": "stats_inference",
        "followups": [
            {"task_id": "seed_etl_functional", "kind": "sibling"},
            {"task_id": "seed_bootstrap_ci", "kind": "sibling"},
            {"task_id": "seed_ttest_pvalue", "kind": "sibling"},
        ],
        "prompt": (
            "Implement a z-score anomaly detector. Given a list of values, compute the mean and sample "
            "standard deviation, then return the indices of values whose absolute z-score exceeds a "
            "threshold (default 3.0). Handle constant data (zero standard deviation) by flagging no "
            "anomalies."
        ),
        "scaffold": (
            "def zscore_anomalies(values: list[float], threshold: float = 3.0) -> list[int]:\n"
            "    # TODO: return list of anomaly indices\n"
            "    pass\n"
        ),
        "difficulty": 1,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "missing_outliers", "secondary": ["distributions"]},
        "task_type": "apply",
        "context_notes": (
            "Outliers are extreme values that can skew statistics or model training. A z-score measures "
            "how many standard deviations a value is from the mean, so large absolute z-scores flag "
            "anomalies. This assumes the data is roughly Gaussian. Outlier detection is a "
            "data-cleaning prerequisite before modeling."
        ),
    },
    {
        "slug": "cosine_lr",
        "cluster": "training_dynamics",
        "followups": [
            {"task_id": "seed_adam", "kind": "sibling"},
            {"task_id": "seed_backprop_mlp", "kind": "prereq"},
        ],
        "prompt": (
            "Implement a cosine annealing learning-rate schedule with linear warm-up. Given the current "
            "step t, total steps T, warm-up steps W, and initial/final learning rates, return the "
            "learning rate at step t: linear ramp up to lr_init during warm-up (if t < W), then cosine "
            "decay from lr_init down to lr_final over the remaining steps."
        ),
        "scaffold": (
            "import math\n\n\n"
            "def lr_at_step(t: int, total_steps: int, warmup_steps: int, lr_init: float = 0.001, lr_final: float = 0.0) -> float:\n"
            "    # TODO: return learning rate at step t\n"
            "    pass\n"
        ),
        "difficulty": 2,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "lr_scheduling", "secondary": ["gradient_descent_sgd"]},
        "task_type": "implement",
        "context_notes": (
            "Learning-rate schedules adjust the step size during training to speed up early progress "
            "and refine later. Warm-up starts small to avoid destabilizing early gradients, then a "
            "cosine curve decays smoothly to the final rate. Decaying the learning rate helps gradient "
            "descent settle into a good optimum. Schedule shape is a key hyperparameter in deep-learning "
            "training."
        ),
    },
    {
        "slug": "thread_queue",
        "cluster": "data_eng",
        "followups": [
            {"task_id": "seed_etl_functional", "kind": "sibling"},
        ],
        "prompt": (
            "Implement a thread-safe bounded queue. Use a collections.deque, a threading.Lock, and two "
            "threading.Condition variables so put() blocks when full and get() blocks when empty. Both "
            "methods accept an optional timeout (seconds); put returns True on success and False on "
            "timeout, and get returns the item or None on timeout."
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
        "hints": [],
        "tags": {"primary": "data_structures", "secondary": ["generators_iterators"]},
        "task_type": "implement",
        "context_notes": (
            "A bounded queue synchronizes producers and consumers with a fixed capacity. Thread-safety "
            "requires a lock around every mutation and condition variables to wake waiters when space "
            "or items appear. Blocking with timeout avoids deadlock when producers or consumers stall. "
            "This pattern is the basis of producer-consumer pipelines, and consuming items one at a time "
            "is naturally expressed with generators."
        ),
    },
    {
        "slug": "quantize_int8",
        "cluster": "llm_stack",
        "followups": [
            {"task_id": "seed_kv_cache", "kind": "sibling"},
            {"task_id": "seed_drift_psi", "kind": "sibling"},
            {"task_id": "seed_finetune_head", "kind": "sibling"},
        ],
        "prompt": (
            "Implement symmetric int8 quantization. Given a list of floats, compute scale = max(abs(x)) "
            "/ 127, quantize each value to round(value / scale) clamped to [-127, 127], and return "
            "(quantized, scale). Also implement dequantize(qvalues, scale) that recovers approximate "
            "floats. Guard against all-zero input by using scale = 1.0."
        ),
        "scaffold": (
            "def quantize_int8(values: list[float]) -> tuple[list[int], float]:\n"
            "    # TODO: return (int8 values, scale)\n"
            "    pass\n\n\n"
            "def dequantize_int8(qvalues: list[int], scale: float) -> list[float]:\n"
            "    # TODO: return recovered floats\n"
            "    pass\n"
        ),
        "difficulty": 2,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "quantization", "secondary": ["deployment_serving"]},
        "task_type": "implement",
        "context_notes": (
            "Quantization stores weights and activations in low precision (often int8) to shrink models "
            "and speed up inference. Symmetric quantization maps [-scale, scale] to [-127, 127] by "
            "dividing by a single scale factor. Dequantization multiplies back by the scale, "
            "introducing a small rounding error. It is a standard serving optimization for deploying "
            "models at scale."
        ),
    },
    {
        "slug": "drift_psi",
        "cluster": "eval_mlops",
        "followups": [
            {"task_id": "seed_metrics_cm", "kind": "sibling"},
            {"task_id": "seed_explain_permutation", "kind": "sibling"},
        ],
        "prompt": (
            "Implement the population stability index (PSI) and a KS-style drift score between two "
            "binned score distributions. Given expected and observed bucket proportions (each a list "
            "of floats summing to ~1), compute PSI = sum((obs - exp) * ln(obs / exp)) and the KS "
            "statistic = max absolute difference of the cumulative distributions. Use a small epsilon "
            "(1e-6) for zero counts. Return (psi, ks)."
        ),
        "scaffold": (
            "import math\n\n\n"
            "def drift_scores(expected_props: list[float], observed_props: list[float], eps: float = 1e-6) -> tuple[float, float]:\n"
            "    # TODO: return (psi, ks_stat)\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "monitoring_drift", "secondary": ["metrics_classification"]},
        "task_type": "apply",
        "context_notes": (
            "Model monitoring watches for drift: when the distribution of model inputs or outputs "
            "changes from what the model was trained on. PSI measures how much one bucketed "
            "probability distribution differs from another, with small values meaning stable. The KS "
            "statistic is the maximum gap between cumulative distributions. Both are early-warning "
            "signals that a deployed model may need retraining."
        ),
    },
    {
        "slug": "etl_functional",
        "cluster": "data_eng",
        "followups": [
            {"task_id": "seed_thread_queue", "kind": "sibling"},
            {"task_id": "seed_zscore_anomaly", "kind": "prereq"},
        ],
        "prompt": (
            "Implement a small ETL pipeline in functional style. Given a list of raw dict rows (keys "
            "'name', 'amount', 'tag'), (1) filter out rows with non-positive amounts, (2) map each "
            "surviving row to a (tag, amount) pair, and (3) reduce the pairs into a dict mapping tag "
            "to total amount. Use filter/map/reduce semantics only (no mutable accumulators or loops)."
        ),
        "scaffold": (
            "from functools import reduce\n\n\n"
            "def etl_pipeline(rows: list[dict]) -> dict[str, float]:\n"
            "    # TODO: return {tag: total_amount}\n"
            "    pass\n"
        ),
        "difficulty": 2,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "functional", "secondary": ["pandas_cleaning", "joins_merges"]},
        "task_type": "apply",
        "context_notes": (
            "Functional style expresses data pipelines as composed pure operations: filter, map, "
            "reduce. Each step transforms an immutable value into the next, which is easy to test and "
            "reason about. Cleaning (dropping invalid rows) and aggregation (grouping by tag) are the "
            "core of an ETL pipeline. The same ideas underpin joins and merges when multiple sources "
            "must be combined."
        ),
    },
    {
        "slug": "tree_gini",
        "cluster": "classical_ml",
        "followups": [
            {"task_id": "seed_knn_weighted", "kind": "sibling"},
            {"task_id": "seed_metrics_cm", "kind": "sibling"},
            {"task_id": "seed_explain_permutation", "kind": "sibling"},
            {"task_id": "seed_kfold", "kind": "sibling"},
        ],
        "prompt": (
            "Implement the split-finding step of a decision tree. Given a list of feature values and "
            "binary labels, evaluate every midpoint between consecutive sorted unique feature values as "
            "a threshold and return the (threshold, weighted_gini_impurity) pair with the lowest "
            "weighted Gini impurity. Gini(node) = 1 - sum(p^2) over class proportions. If no valid "
            "threshold exists, return (None, 1.0)."
        ),
        "scaffold": (
            "def best_gini_split(features: list[float], labels: list[int]) -> tuple[float | None, float]:\n"
            "    # TODO: return (best_threshold, best_weighted_gini)\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "trees_ensembles", "secondary": ["feature_construction"]},
        "task_type": "implement",
        "context_notes": (
            "Decision trees recursively split the data to separate classes, choosing the split that "
            "most reduces impurity. Gini impurity measures how mixed a node's labels are, and the best "
            "threshold minimizes the weighted impurity of the two child nodes. Feature construction — "
            "choosing good candidate features to split on — determines what the tree can learn. "
            "Ensembles combine many such trees to reduce variance."
        ),
    },
    {
        "slug": "knn_weighted",
        "cluster": "classical_ml",
        "followups": [
            {"task_id": "seed_pca_svd", "kind": "prereq"},
            {"task_id": "seed_oversample", "kind": "prereq"},
            {"task_id": "seed_kmeans", "kind": "sibling"},
        ],
        "prompt": (
            "Implement k-nearest-neighbors prediction with distance-weighted voting. Given a list of "
            "training points as ((x, y), label) tuples and a new query point, find the k nearest "
            "neighbors and predict the label by weighting each neighbor's vote by 1/distance. If a "
            "neighbor has distance 0, return its label immediately. Break ties toward the lower label."
        ),
        "scaffold": (
            "def knn_predict(train: list[tuple[tuple[float, float], int]], point: tuple[float, float], k: int = 3) -> int:\n"
            "    # TODO: return predicted label\n"
            "    pass\n"
        ),
        "difficulty": 2,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "knn_svm_naivebayes", "secondary": ["scaling_encoding"]},
        "task_type": "apply",
        "context_notes": (
            "K-nearest neighbors classifies a point by the majority label of its k closest training "
            "points. Distance-weighted voting gives closer neighbors more influence than far ones. KNN "
            "needs no training, but it is sensitive to feature scaling, since unscaled features "
            "dominate the distance. It is a common lazy-learning baseline."
        ),
    },
    {
        "slug": "ttest_pvalue",
        "cluster": "stats_inference",
        "followups": [
            {"task_id": "seed_bootstrap_ci", "kind": "sibling"},
            {"task_id": "seed_zscore_anomaly", "kind": "sibling"},
            {"task_id": "seed_linreg_r2", "kind": "sibling"},
        ],
        "prompt": (
            "Implement a one-sample t-test and return the t statistic and a two-sided p-value. Given a "
            "sample and a hypothesized mean mu0, compute t = (mean - mu0) / (std / sqrt(n)) using the "
            "sample standard deviation with n-1 degrees of freedom. Compute the two-sided p-value with "
            "the normal approximation via the error function: p = erfc(|t| / sqrt(2)). Do not import "
            "scipy. Return (t, p)."
        ),
        "scaffold": (
            "import math\n\n\n"
            "def ttest(sample: list[float], mu0: float = 0.0) -> tuple[float, float]:\n"
            "    # TODO: return (t_stat, p_value)\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "hypothesis_pvalue", "secondary": ["bayes_mle", "distributions"]},
        "task_type": "apply",
        "context_notes": (
            "Hypothesis testing asks whether an observed effect is larger than chance would produce. "
            "The t-statistic standardizes the sample mean's deviation by its standard error. The "
            "p-value is the probability of observing a t-statistic at least this extreme under the "
            "null hypothesis, and small p-values reject the null. The distribution of the sample mean "
            "(Gaussian for large n) is the prerequisite; maximum-likelihood estimation provides the "
            "parameter estimates used inside."
        ),
    },
    {
        "slug": "ridge_l2",
        "cluster": "training_dynamics",
        "followups": [
            {"task_id": "seed_linreg_r2", "kind": "prereq"},
            {"task_id": "seed_adam", "kind": "sibling"},
            {"task_id": "seed_grid_search", "kind": "sibling"},
        ],
        "prompt": (
            "Implement ridge (L2-regularized) linear regression trained by gradient descent. Given a "
            "numpy feature matrix X (with an added bias column of ones) and target vector y, run T "
            "steps of gradient descent on MSE + lam * sum(w^2) with a fixed learning rate, and return "
            "the weight vector. Initialize weights to zeros."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def ridge_gd(X: np.ndarray, y: np.ndarray, lam: float = 0.1, lr: float = 0.01, steps: int = 200) -> np.ndarray:\n"
            "    # TODO: return weight vector\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "regularization", "secondary": ["gradient_descent_sgd"]},
        "task_type": "implement",
        "context_notes": (
            "Regularization adds a penalty on weight magnitude to the loss, discouraging overfitting by "
            "keeping the model simple. Ridge (L2) penalizes the sum of squared weights, shrinking them "
            "toward zero without setting them to zero. Gradient descent then minimizes the regularized "
            "objective directly. The regularization strength lambda trades bias against variance."
        ),
    },
    {
        "slug": "overfit_holdout",
        "cluster": "eval_mlops",
        "followups": [
            {"task_id": "seed_ridge_l2", "kind": "sibling"},
            {"task_id": "seed_kfold", "kind": "sibling"},
            {"task_id": "seed_grid_search", "kind": "sibling"},
        ],
        "prompt": (
            "Implement an overfitting detector. Given x and y lists and a polynomial degree, fit a "
            "least-squares polynomial on the first (1 - test_frac) fraction of the data, then compute "
            "train MSE on the training portion and test MSE on the held-out portion. Return "
            "(train_mse, test_mse). A large gap between them signals overfitting."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def train_test_gap(x: list[float], y: list[float], degree: int, test_frac: float = 0.3) -> tuple[float, float]:\n"
            "    # TODO: return (train_mse, test_mse)\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "overfitting_underfitting", "secondary": ["data_leakage_calibration"]},
        "task_type": "apply",
        "context_notes": (
            "Overfitting is when a model memorizes the training data and fails on new data, showing a "
            "big train/test performance gap. Evaluating on a held-out test set that the model never "
            "saw is the only honest measure of generalization. Data leakage — letting test information "
            "leak into training — inflates those estimates and is a calibration hazard. The "
            "training/test split is the guard against both."
        ),
    },
    {
        "slug": "adam",
        "cluster": "training_dynamics",
        "followups": [
            {"task_id": "seed_cosine_lr", "kind": "sibling"},
            {"task_id": "seed_backprop_mlp", "kind": "prereq"},
            {"task_id": "seed_grid_search", "kind": "sibling"},
        ],
        "prompt": (
            "Implement one Adam update step. Given a gradient g and the first/second moment "
            "accumulators m and v, update m = beta1*m + (1-beta1)*g, v = beta2*v + (1-beta2)*g^2, apply "
            "bias correction (divide by 1 - beta^t), and return the updated parameter, m, and v using "
            "param_new = param - lr * m_hat / (sqrt(v_hat) + eps)."
        ),
        "scaffold": (
            "def adam_step(param: float, grad: float, m: float, v: float, t: int, lr: float = 0.001, beta1: float = 0.9, beta2: float = 0.999, eps: float = 1e-8) -> tuple[float, float, float]:\n"
            "    # TODO: return (param_new, m_new, v_new)\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "optimizers_adam", "secondary": ["lr_scheduling"]},
        "task_type": "implement",
        "context_notes": (
            "Adam is an adaptive optimizer that keeps per-parameter momentum (first moment) and a "
            "running mean of squared gradients (second moment). Bias correction makes the early "
            "moments accurate, and the effective step size is normalized by the square root of the "
            "second moment. Adam is robust to learning-rate choices and is the default optimizer in "
            "deep learning. Learning-rate schedules still apply on top of it."
        ),
    },
    {
        "slug": "grid_search",
        "cluster": "training_dynamics",
        "followups": [
            {"task_id": "seed_kfold", "kind": "sibling"},
            {"task_id": "seed_adam", "kind": "sibling"},
            {"task_id": "seed_cosine_lr", "kind": "sibling"},
        ],
        "prompt": (
            "Implement a grid search over candidate learning rates. Given a list of candidates, a "
            "train_fn(candidate) -> model, and a validate_fn(model) -> score, train a model for each "
            "candidate, score it on validation, and return (best_candidate, best_score). Keep the "
            "first candidate on ties. Higher scores are better."
        ),
        "scaffold": (
            "def grid_search(candidates: list[float], train_fn, validate_fn) -> tuple[float, float]:\n"
            "    # TODO: return (best_candidate, best_score)\n"
            "    pass\n"
        ),
        "difficulty": 2,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "hyperparameter_tuning", "secondary": ["cross_validation"]},
        "task_type": "apply",
        "context_notes": (
            "Hyperparameters control the learning process itself (learning rate, regularization "
            "strength) and are not learned from data. Grid search tries every combination on a "
            "validation set and keeps the one with the best score. It pairs with cross-validation so "
            "the choice is not overfit to a single split. The search budget grows quickly, so the "
            "candidate list is kept small."
        ),
    },
    {
        "slug": "conv2d",
        "cluster": "dl_architectures",
        "followups": [
            {"task_id": "seed_backprop_mlp", "kind": "prereq"},
            {"task_id": "seed_softmax", "kind": "sibling"},
        ],
        "prompt": (
            "Implement a 2D convolution for a single input channel and a single kernel with padding and "
            "stride. Given an input matrix and a kernel matrix, apply zero padding, slide the kernel "
            "by stride, and return the output matrix of the correct size: out = (in + 2*pad - k) // "
            "stride + 1. Return a numpy array."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def conv2d_single(x: np.ndarray, kernel: np.ndarray, padding: int = 0, stride: int = 1) -> np.ndarray:\n"
            "    # TODO: return output matrix\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "cnn", "secondary": ["activation_normalization"]},
        "task_type": "implement",
        "context_notes": (
            "Convolutional layers slide a small kernel over the input, computing local dot products to "
            "detect patterns regardless of position. Padding preserves the spatial size, and stride "
            "controls how densely the kernel is sampled. A stack of convolutions followed by nonlinear "
            "activations and normalization builds a CNN's feature hierarchy. Each output is a weighted "
            "sum over the kernel's receptive field."
        ),
    },
    {
        "slug": "lstm_cell",
        "cluster": "dl_architectures",
        "followups": [
            {"task_id": "seed_backprop_mlp", "kind": "prereq"},
            {"task_id": "seed_softmax", "kind": "sibling"},
        ],
        "prompt": (
            "Implement one LSTM cell forward pass. Given input x, previous hidden state h_prev, "
            "previous cell state c_prev, and combined weight matrices W (input), U (recurrent) and "
            "bias b, compute the four gates (input, forget, cell candidate, output) from W@x + U@h_prev "
            "+ b. Use sigmoid for the input/forget/output gates and tanh for the candidate. Update "
            "c = f*c_prev + i*cand, h = o*tanh(c). Return (h, c)."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def sigmoid(z):\n"
            "    return 1.0 / (1.0 + np.exp(-z))\n\n\n"
            "def lstm_cell(x: np.ndarray, h_prev: np.ndarray, c_prev: np.ndarray, W: np.ndarray, U: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:\n"
            "    # TODO: return (h_new, c_new)\n"
            "    pass\n"
        ),
        "difficulty": 4,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "rnn_lstm", "secondary": ["activation_normalization"]},
        "task_type": "implement",
        "context_notes": (
            "Recurrent networks process sequences by carrying a hidden state across time steps. An LSTM "
            "adds a cell state that the input, forget, and output gates can add to or erase, solving "
            "the vanishing-gradient problem of plain RNNs. Each step combines the current input with "
            "the previous hidden state through gated computations. The gates use sigmoid activations so "
            "their values behave like differentiable switches."
        ),
    },
    {
        "slug": "bpe",
        "cluster": "llm_stack",
        "followups": [
            {"task_id": "seed_attention", "kind": "sibling"},
            {"task_id": "seed_finetune_head", "kind": "sibling"},
        ],
        "prompt": (
            "Implement the core of byte-pair encoding: count adjacent token-pair frequencies across a "
            "tokenized corpus (a list of lists of ints), find the most frequent pair, and return it "
            "along with a new corpus where every occurrence of that pair is merged into a single new "
            "token id (the current max token id + 1). Break frequency ties by the lexicographically "
            "smaller pair."
        ),
        "scaffold": (
            "def bpe_merge(corpus: list[list[int]]) -> tuple[tuple[int, int], list[list[int]]]:\n"
            "    # TODO: return (most_frequent_pair, corpus_with_pair_merged)\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "tokenization_bpe", "secondary": ["data_structures"]},
        "task_type": "implement",
        "context_notes": (
            "Subword tokenization splits text into pieces that balance vocabulary size and coverage. "
            "Byte-pair encoding iteratively merges the most frequent adjacent token pair, learning "
            "common subwords like 'ing' or 'tion'. The result is a fixed vocabulary of tokens the model "
            "can embed. Dictionary and counting structures make the merge efficient."
        ),
    },
    {
        "slug": "finetune_head",
        "cluster": "llm_stack",
        "followups": [
            {"task_id": "seed_softmax", "kind": "prereq"},
            {"task_id": "seed_backprop_mlp", "kind": "prereq"},
            {"task_id": "seed_quantize_int8", "kind": "sibling"},
        ],
        "prompt": (
            "Implement the gradient update for fine-tuning a classifier head while the backbone is "
            "frozen. Given fixed backbone feature vectors (a numpy matrix), one-hot labels, and a "
            "trainable head weight matrix W, take one gradient descent step on the softmax cross-entropy "
            "loss over logits = features @ W. Only W is updated (the backbone is frozen). Return the "
            "updated W."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def finetune_head(features: np.ndarray, y_onehot: np.ndarray, W: np.ndarray, lr: float = 0.1) -> np.ndarray:\n"
            "    # TODO: return updated W (backbone is frozen)\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "pretraining_finetuning", "secondary": ["loss_functions"]},
        "task_type": "implement",
        "context_notes": (
            "Pretrained models learn general representations on large corpora, and fine-tuning adapts "
            "them to a specific task. A common strategy freezes the backbone's parameters and trains "
            "only a new classification head on the task data, which is fast and needs little data. The "
            "head uses cross-entropy over logits. Because the backbone weights are frozen, only the "
            "head's gradients are computed and applied."
        ),
    },
    {
        "slug": "explain_permutation",
        "cluster": "eval_mlops",
        "followups": [
            {"task_id": "seed_tree_gini", "kind": "sibling"},
            {"task_id": "seed_drift_psi", "kind": "sibling"},
        ],
        "prompt": (
            "Implement permutation feature importance. Given a feature matrix X, labels y, a predictor "
            "(callable returning predictions), and a metric (callable on y_true, y_pred, higher is "
            "better), compute the baseline score, then for each feature column shuffle that column's "
            "values (fixed seed) and record the score drop = baseline - shuffled_score. Return a list "
            "of importance scores, one per column."
        ),
        "scaffold": (
            "import numpy as np\n\n\n"
            "def permutation_importance(X: np.ndarray, y: np.ndarray, predict, metric, seed: int = 0) -> list[float]:\n"
            "    # TODO: return importance per feature column\n"
            "    pass\n"
        ),
        "difficulty": 3,
        "max_score": 5,
        "hints": [],
        "tags": {"primary": "explainability", "secondary": ["reproducibility_tracking"]},
        "task_type": "apply",
        "context_notes": (
            "Explainability answers why a model made its predictions. Permutation importance measures "
            "how much the model's performance drops when a feature's values are shuffled, breaking its "
            "relationship with the target. A large drop means the feature matters. Shuffling with a "
            "fixed seed makes the measurement reproducible and comparable across runs."
        ),
    },
]


def _row_tuple(seed: dict[str, Any]) -> tuple:
    """Convert a catalog entry into an INSERT row tuple."""
    return (
        f"seed_{seed['slug']}",
        SYSTEM_OWNER,
        seed["prompt"],
        seed.get("scaffold"),
        max(1, min(5, int(seed.get("difficulty", 2)))),
        int(seed.get("max_score", 5)),
        json.dumps(seed.get("hints") or []),
        (seed.get("context_notes") or "").strip()[:2000],
        json.dumps(seed["tags"]),
        seed.get("task_type", "implement"),
        "seed",
        None,
        None,
        (seed.get("cluster") or "").strip()[:64] or None,
        json.dumps(seed.get("followups") or []),
        1,
        str(_utcnow_naive()),
    )


_TASK_COLUMNS = (
    "id", "owner", "prompt", "scaffold", "difficulty", "max_score",
    "hints_json", "context_notes", "tags_json", "task_type", "source",
    "parent_task_id", "target_text", "cluster_id", "followups_json",
    "is_public", "created_at",
)


def seed_question_bank() -> int:
    """Idempotently insert the builtin catalog. Returns number inserted.

    Hermetic: no network, no model calls — ``context_notes`` are pre-authored.
    Single batched ``INSERT OR IGNORE`` (one transaction for the whole
    catalog). ``INSERT OR IGNORE`` is keyed on the primary key, so a
    human-edited seed row is never overwritten and re-runs are no-ops.
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
    with sqlite_conn() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount


def _seed_rows() -> list[dict]:
    """Tasks in the DB that are seeds (source seed/seed_llm)."""
    from coach.db import create_schema, learner_session
    from coach.tasks import TaskModel, task_to_dict
    from sqlalchemy import select

    create_schema()
    session = learner_session()
    try:
        rows = session.scalars(
            select(TaskModel).where(TaskModel.source.in_(["seed", "seed_llm"]))
        ).all()
        return [task_to_dict(m) for m in rows]
    finally:
        session.close()


def _attempts_by_tag() -> dict[str, dict[str, int]]:
    """Per-tag/per-family -> {candidate: attempt_count} across all tasks.

    Derived from ``session_steps`` joined on the task's tags (primary or
    secondary). Used by ``coverage_report`` for per-candidate asked counts.
    """
    from coach.db import create_schema, learner_session
    from coach.steps import SessionStepModel
    from coach.tasks import TaskModel, parse_tags
    from sqlalchemy import select

    create_schema()
    session = learner_session()
    try:
        tasks = session.execute(select(TaskModel.id, TaskModel.tags_json)).all()
        attempts = session.execute(
            select(SessionStepModel.candidate, SessionStepModel.task_id)
        ).all()
        tag_map: dict[str, list[str]] = {}
        for task_id, tags_json in tasks:
            tags = parse_tags(tags_json)
            tag_map[task_id] = [tags.get("primary")] + list(tags.get("secondary") or [])
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
    any seed task.
    """
    from coach.taxonomy import TAGS as _TAGS

    seeds = _seed_rows()
    by_tag: dict[str, list[str]] = {tag: [] for tag in ALL_TAGS}
    by_family: dict[str, list[str]] = {fam: [] for fam in FAMILIES}
    for t in seeds:
        tags = t.get("tags") or {}
        for tag in [tags.get("primary")] + list(tags.get("secondary") or []):
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
                hints=seed.get("hints", []),
                context_notes=seed.get("context_notes", ""),
                tags=seed["tags"],
                task_type=seed.get("task_type", "implement"),
                source="seed_llm",
                is_public=True,
                task_id=tid,
                cluster_id=TAG_TO_FAMILY.get(tag),
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