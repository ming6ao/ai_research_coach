"""Closed 3-level ML/AI topic vocabulary for task tagging.

Single source of truth for the taxonomy. Every task carries a ``tags`` block::

    {"primary": <skill>, "secondary": [<skill>, ...]}

with exactly one primary **leaf skill** and 0-2 secondary leaf skills.

The hierarchy has three levels::

    domain  ->  area  ->  skill (leaf)

``global`` is the candidate's overall belief (not a taxonomy node). Beliefs
are tracked at every level; only the primary leaf skill feeds the estimator
(one answer updates the skill, its area, its domain, and the global belief).

``validate`` is the server-side gate: an unknown or missing primary, or a
non-leaf primary, is rejected (422 on create/PATCH). There is no permissive
fallback — an uncategorized task must not be created.
"""

from __future__ import annotations

# Domains (3) -> areas (18) -> skills (leaves). The vocabulary is deliberately
# limited to code-gradable topics that are still current and load-bearing for
# frontier AI research (modelling) and systems/infrastructure work.
TAXONOMY: dict[str, dict[str, list[str]]] = {
    "research": {
        "pretraining": [
            "data_mixture",
            "tokenizer_design",
            "pretraining_objectives",
            "scaling_laws",
            "context_length_extension",
            "data_contamination",
        ],
        "post_training": [
            "supervised_finetuning",
            "instruction_tuning",
            "preference_optimization",
            "reward_modeling",
            "rejection_sampling",
            "knowledge_distillation",
            "model_merging",
        ],
        "reinforcement_learning": [
            "policy_gradients",
            "value_based_methods",
            "ppo",
            "grpo",
            "exploration_credit_assignment",
            "offline_rl",
            "environment_reward_design",
            "rl_for_reasoning",
        ],
        "architectures": [
            "attention_variants",
            "mixture_of_experts",
            "positional_encoding",
            "normalization",
            "state_space_models",
            "long_context",
            "parameter_efficient_finetuning",
        ],
        "generative_modeling": [
            "diffusion_models",
            "flow_matching",
            "variational_autoencoders",
            "sampling_decoding",
        ],
        "multimodal": [
            "vision_encoders",
            "vision_language_alignment",
            "audio_speech",
            "video_modeling",
        ],
        "agents": [
            "tool_use",
            "planning_decomposition",
            "memory_context",
            "retrieval_augmented_generation",
            "multi_agent_systems",
        ],
        "evaluation": [
            "benchmark_design",
            "contamination_detection",
            "capability_elicitation",
            "red_teaming",
            "statistical_evaluation",
            "human_model_grading",
        ],
        "research_method": [
            "experiment_design",
            "ablations",
            "reproducibility",
            "error_analysis",
            "literature_grounding",
        ],
    },
    "systems": {
        "kernels_and_gpu": [
            "cuda_programming",
            "triton",
            "simd_warp_primitives",
            "memory_coalescing",
            "fused_kernels",
            "flash_attention",
            "gemm_reductions",
            "kernel_profiling",
            "custom_autograd",
        ],
        "distributed_training": [
            "data_parallelism",
            "tensor_parallelism",
            "pipeline_parallelism",
            "sharding_and_offload",
            "collectives_and_overlap",
            "fault_tolerance",
            "distributed_checkpointing",
            "expert_parallelism",
        ],
        "inference_and_serving": [
            "continuous_batching",
            "kv_cache_management",
            "paged_attention",
            "speculative_decoding",
            "quantization",
            "serving_engine_internals",
            "autoscaling_routing",
            "disaggregated_serving",
        ],
        "performance_engineering": [
            "profiling_roofline",
            "operator_fusion",
            "compilation",
            "mixed_precision",
            "memory_optimization",
            "autotuning",
        ],
        "hardware": [
            "gpu_architecture",
            "memory_hierarchy",
            "interconnects_topology",
            "accelerators",
            "energy_thermal",
        ],
        "data_and_storage_infra": [
            "streaming_datasets",
            "sharding_formats",
            "caching",
            "data_loading_pipelines",
            "distributed_io",
            "storage_systems",
        ],
        "ml_platform": [
            "orchestration_scheduling",
            "experiment_tracking",
            "ci_cd_for_models",
            "monitoring_drift",
            "reproducibility_artifacts",
            "cost_capacity",
        ],
    },
    "foundations": {
        "math": [
            "linear_algebra",
            "calculus_autodiff",
            "probability_statistics",
            "optimization_theory",
            "information_theory",
            "numerical_stability",
        ],
        "software_engineering": [
            "concurrency_async",
            "memory_management",
            "testing",
            "packaging_tooling",
        ],
    },
}

DOMAINS: list[str] = list(TAXONOMY.keys())

# area -> its domain
AREA_TO_DOMAIN: dict[str, str] = {
    area: domain for domain, areas in TAXONOMY.items() for area in areas
}

# area -> leaf skills
AREAS: dict[str, list[str]] = {
    area: list(skills) for areas in TAXONOMY.values() for area, skills in areas.items()
}

# leaf skill -> its area; leaf skill -> its domain
SKILL_TO_AREA: dict[str, str] = {
    skill: area for area, skills in AREAS.items() for skill in skills
}
SKILL_TO_DOMAIN: dict[str, str] = {
    skill: AREA_TO_DOMAIN[area] for skill, area in SKILL_TO_AREA.items()
}

NODE_PARENT: dict[str, str | None] = {}
NODE_LEVEL: dict[str, int] = {}
NODE_CHILDREN: dict[str, list[str]] = {}

for _domain, _areas in TAXONOMY.items():
    NODE_PARENT[_domain] = None
    NODE_LEVEL[_domain] = 1
    NODE_CHILDREN[_domain] = list(_areas.keys())
    for _area, _skills in _areas.items():
        NODE_PARENT[_area] = _domain
        NODE_LEVEL[_area] = 2
        NODE_CHILDREN[_area] = list(_skills)
        for _skill in _skills:
            NODE_PARENT[_skill] = _area
            NODE_LEVEL[_skill] = 3
            NODE_CHILDREN[_skill] = []

# Ordered lists (parents always precede children).
AREA_NODES: list[str] = [area for domain in DOMAINS for area in TAXONOMY[domain]]
LEAF_NODES: list[str] = [skill for area in AREA_NODES for skill in AREAS[area]]
ALL_NODES: list[str] = DOMAINS + AREA_NODES + LEAF_NODES

# Convenience canonical tag lists (validation/iteration).
ALL_TAGS: list[str] = list(LEAF_NODES)

# Synonym/alternate-name map -> canonical node id (usually a leaf). Keeps LLM
# categorization and human entry robust to near-duplicate phrasing.
ALIASES: dict[str, str] = {
    # pretraining / post-training
    "pretraining": "pretraining_objectives",
    "pretraining_finetuning": "pretraining_objectives",
    "finetuning": "supervised_finetuning",
    "fine_tuning": "supervised_finetuning",
    "sft": "supervised_finetuning",
    "dpo": "preference_optimization",
    "rlhf": "reward_modeling",
    "distillation": "knowledge_distillation",
    "tokenization": "tokenizer_design",
    "tokenization_bpe": "tokenizer_design",
    "bpe": "tokenizer_design",
    "context_extension": "context_length_extension",
    # rl
    "rl": "policy_gradients",
    "reinforcement_learning": "policy_gradients",
    "policy_gradient": "policy_gradients",
    "reward_shaping": "environment_reward_design",
    "credit_assignment": "exploration_credit_assignment",
    # architectures
    "attention": "attention_variants",
    "attention_transformer": "attention_variants",
    "transformer": "attention_variants",
    "self_attention": "attention_variants",
    "moe": "mixture_of_experts",
    "rope": "positional_encoding",
    "layer_norm": "normalization",
    "rmsnorm": "normalization",
    "rnn_lstm": "state_space_models",
    "ssm": "state_space_models",
    "lora": "parameter_efficient_finetuning",
    "peft": "parameter_efficient_finetuning",
    # generative / multimodal
    "diffusion": "diffusion_models",
    "vae": "variational_autoencoders",
    "decoding": "sampling_decoding",
    "cnn": "vision_encoders",
    "vit": "vision_encoders",
    "clip": "vision_language_alignment",
    "vlm": "vision_language_alignment",
    # agents
    "rag": "retrieval_augmented_generation",
    "retrieval": "retrieval_augmented_generation",
    "tool_calling": "tool_use",
    "function_calling": "tool_use",
    "planning": "planning_decomposition",
    # evaluation / method
    "metrics_classification": "benchmark_design",
    "cross_validation": "statistical_evaluation",
    "calibration": "statistical_evaluation",
    "leakage": "contamination_detection",
    "data_leakage": "contamination_detection",
    "significance": "statistical_evaluation",
    "ablation": "ablations",
    "experiment_tracking": "experiment_tracking",
    "hyperparameter_tuning": "experiment_design",
    # kernels / systems
    "cuda": "cuda_programming",
    "gpu_kernel": "cuda_programming",
    "flash_attn": "flash_attention",
    "memory_banking": "memory_coalescing",
    "roofline": "profiling_roofline",
    "profiling": "profiling_roofline",
    "torch_compile": "compilation",
    "quantize": "quantization",
    "kv_cache": "kv_cache_management",
    "batching": "continuous_batching",
    "speculative": "speculative_decoding",
    "data_parallel": "data_parallelism",
    "tensor_parallel": "tensor_parallelism",
    "pipeline_parallel": "pipeline_parallelism",
    "fsdp": "sharding_and_offload",
    "zero": "sharding_and_offload",
    "all_reduce": "collectives_and_overlap",
    "checkpointing": "distributed_checkpointing",
    "deployment": "serving_engine_internals",
    "serving": "serving_engine_internals",
    "inference": "serving_engine_internals",
    "drift": "monitoring_drift",
    "monitoring": "monitoring_drift",
    "orchestration": "orchestration_scheduling",
    "scheduling": "orchestration_scheduling",
    "reproducibility_tracking": "reproducibility_artifacts",
    "mlflow": "experiment_tracking",
    # foundations
    "backprop": "calculus_autodiff",
    "backpropagation": "calculus_autodiff",
    "autodiff": "calculus_autodiff",
    "gradient_descent_sgd": "optimization_theory",
    "sgd": "optimization_theory",
    "adam": "optimization_theory",
    "optimizers_adam": "optimization_theory",
    "distributions": "probability_statistics",
    "bayes_mle": "probability_statistics",
    "loss_functions": "pretraining_objectives",
    "regularization": "optimization_theory",
    "numerical_precision": "numerical_stability",
    "async": "concurrency_async",
    "threading": "concurrency_async",
    "unit_testing": "testing",
    "packaging": "packaging_tooling",
}

# Task types (each is still implemented as a code task judged normally).
TASK_TYPES = ("implement", "apply", "debug", "design", "analyze")


def _canon(name: str | None) -> str:
    return str(name or "").strip().lower().replace("-", "_").replace(" ", "_")


def resolve_node(name: str | None) -> str | None:
    """Resolve a name/alias to a canonical node id (domain, area, or skill)."""
    key = _canon(name)
    if not key:
        return None
    if key in NODE_LEVEL:
        return key
    return ALIASES.get(key)


# Backwards-compatible name (used by task filters / LLM output sanitization).
normalize_tag = resolve_node


def is_node(node: str | None) -> bool:
    return resolve_node(node) is not None


def is_leaf(node: str | None) -> bool:
    canon = resolve_node(node)
    return canon is not None and NODE_LEVEL.get(canon, 0) == 3


def is_domain(node: str | None) -> bool:
    canon = resolve_node(node)
    return canon is not None and NODE_LEVEL.get(canon, 0) == 1


def is_area(node: str | None) -> bool:
    canon = resolve_node(node)
    return canon is not None and NODE_LEVEL.get(canon, 0) == 2


def normalize_node(name: str | None) -> str | None:
    return resolve_node(name)


def level_of(node: str | None) -> int | None:
    canon = resolve_node(node)
    return NODE_LEVEL.get(canon) if canon else None


def parent_of(node: str | None) -> str | None:
    canon = resolve_node(node)
    return NODE_PARENT.get(canon) if canon else None


def path_of(node: str | None) -> list[str]:
    """Root-to-node path (domain, area, skill) for a node, else ``[]``."""
    canon = resolve_node(node)
    if canon is None:
        return []
    out: list[str] = []
    cur: str | None = canon
    while cur is not None:
        out.append(cur)
        cur = NODE_PARENT.get(cur)
    out.reverse()
    return out


def ancestors(node: str | None) -> list[str]:
    """Strict ancestors (root .. parent) for a node, else ``[]``."""
    p = path_of(node)
    return p[:-1] if p else []


def domain_of(node: str | None) -> str | None:
    path = path_of(node)
    return path[0] if path else None


def area_of(node: str | None) -> str | None:
    path = path_of(node)
    return path[1] if len(path) > 1 else None


def validate(tags: dict | None) -> dict:
    """Validate a tags block; returns the canonicalized dict.

    Accepted shape::

        {"primary": <leaf skill>, "secondary": [<leaf skill>, ...]}  (0-2)

    The primary is required and must be a leaf skill; secondary entries must be
    leaves and must not repeat the primary. Raises ``ValueError`` otherwise —
    there is no fallback tag.
    """
    if not isinstance(tags, dict):
        raise ValueError(
            "tags must be an object {primary, secondary}; "
            "a primary tag is required."
        )
    primary_raw = tags.get("primary")
    if not primary_raw:
        raise ValueError("tags.primary is required.")
    primary = resolve_node(primary_raw)
    if primary is None:
        raise ValueError(f"Unknown tag: {primary_raw!r}.")
    if NODE_LEVEL.get(primary, 0) != 3:
        raise ValueError(
            f"tags.primary must be a leaf skill, got {primary_raw!r}."
        )
    secondary_raw = tags.get("secondary") or []
    if not isinstance(secondary_raw, (list, tuple)):
        raise ValueError("tags.secondary must be a list.")
    if len(secondary_raw) > 2:
        raise ValueError("tags.secondary may have at most 2 tags.")
    secondary: list[str] = []
    for raw in secondary_raw:
        canon = resolve_node(raw)
        if canon is None:
            raise ValueError(f"Unknown tag: {raw!r}.")
        if NODE_LEVEL.get(canon, 0) != 3:
            raise ValueError(f"tags.secondary must be leaf skills, got {raw!r}.")
        if canon not in secondary:
            secondary.append(canon)
    if primary in secondary:
        secondary.remove(primary)
    return {"primary": primary, "secondary": secondary}


def format_vocabulary() -> str:
    """Human/LLM-readable rendering of the tree (``domain`` -> ``area`` -> skills)."""
    lines: list[str] = []
    for domain in DOMAINS:
        lines.append(f"{domain}:")
        for area in TAXONOMY[domain]:
            lines.append(f"  {area}: {', '.join(AREAS[area])}")
    return "\n".join(lines)
