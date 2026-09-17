"""Unit tests for the closed 3-level vocabulary in coach.taxonomy."""

from __future__ import annotations

import pytest

from coach.taxonomy import (
    ALL_TAGS,
    AREAS,
    DOMAINS,
    LEAF_NODES,
    NODE_LEVEL,
    NODE_PARENT,
    SKILL_TO_AREA,
    SKILL_TO_DOMAIN,
    TAXONOMY,
    ancestors,
    area_of,
    domain_of,
    family_of,
    format_vocabulary,
    is_area,
    is_domain,
    is_leaf,
    is_valid_family,
    is_valid_tag,
    normalize_tag,
    path_of,
    resolve_node,
    validate,
)


def test_tree_is_three_levels_and_consistent():
    assert DOMAINS and all(NODE_LEVEL[d] == 1 for d in DOMAINS)
    for domain, areas in TAXONOMY.items():
        assert NODE_PARENT[domain] is None
        for area, skills in areas.items():
            assert NODE_PARENT[area] == domain
            assert NODE_LEVEL[area] == 2
            for skill in skills:
                assert NODE_PARENT[skill] == area
                assert NODE_LEVEL[skill] == 3
                assert SKILL_TO_AREA[skill] == area
                assert SKILL_TO_DOMAIN[skill] == domain


def test_leaves_match_area_flattening():
    assert len(LEAF_NODES) == len(set(LEAF_NODES))
    assert ALL_TAGS == LEAF_NODES
    assert set(LEAF_NODES) == {s for skills in AREAS.values() for s in skills}


def test_node_level_predicates():
    assert is_domain("research")
    assert is_area("kernels_and_gpu")
    assert is_leaf("flash_attention")
    assert not is_leaf("kernels_and_gpu")
    assert not is_area("flash_attention")
    assert not is_domain("pretraining")
    assert is_valid_tag("grpo")
    assert not is_valid_tag("systems")
    assert is_valid_family("post_training")
    assert not is_valid_family("grpo")


def test_aliases_resolve_to_canonical():
    assert normalize_tag("attention") == "attention_variants"
    assert normalize_tag("Flash-Attention") == "flash_attention"
    assert normalize_tag("rope") == "positional_encoding"
    assert normalize_tag("dl_arch") == "architectures"
    assert normalize_tag("llm_genai") == "pretraining"
    assert family_of("flash_attention") == "kernels_and_gpu"
    assert area_of("grpo") == "reinforcement_learning"
    assert domain_of("grpo") == "research"


def test_paths_and_ancestors():
    assert path_of("grpo") == ["research", "reinforcement_learning", "grpo"]
    assert ancestors("grpo") == ["research", "reinforcement_learning"]
    assert ancestors("research") == []
    assert path_of("nope") == []


def test_unknown_node_is_invalid():
    assert not is_leaf("quantum_computing")
    assert resolve_node("nope") is None
    assert resolve_node("") is None


def test_validate_requires_primary():
    with pytest.raises(ValueError):
        validate(None)
    with pytest.raises(ValueError):
        validate({})
    with pytest.raises(ValueError):
        validate({"secondary": ["grpo"]})


def test_validate_canonicalizes_and_dedupes():
    assert validate({"primary": "ppo", "secondary": ["grpo", "grpo"]}) == {
        "primary": "ppo",
        "secondary": ["grpo"],
    }


def test_validate_rejects_unknown_and_non_leaf_primary():
    with pytest.raises(ValueError):
        validate({"primary": "bogus"})
    with pytest.raises(ValueError):
        validate({"primary": "systems"})


def test_validate_rejects_unknown_and_non_leaf_secondary():
    with pytest.raises(ValueError):
        validate({"primary": "grpo", "secondary": ["bogus"]})
    with pytest.raises(ValueError):
        validate({"primary": "grpo", "secondary": ["systems"]})


def test_validate_limits_secondary_count():
    with pytest.raises(ValueError):
        validate({"primary": "grpo", "secondary": ["ppo", "dpo", "sft"]})


def test_secondary_removes_primary_duplicate():
    out = validate({"primary": "grpo", "secondary": ["grpo", "ppo"]})
    assert out == {"primary": "grpo", "secondary": ["ppo"]}


def test_format_vocabulary_lists_domains_and_skills():
    text = format_vocabulary()
    assert "research:" in text
    assert "kernels_and_gpu:" in text
    assert "flash_attention" in text
