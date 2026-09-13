"""Unit tests for the closed ML vocabulary in coach.taxonomy."""

from __future__ import annotations

import pytest

from coach.taxonomy import (
    ALL_TAGS,
    FAMILIES,
    TAG_TO_FAMILY,
    TAGS,
    family_of,
    is_valid_family,
    is_valid_tag,
    normalize_tag,
    validate,
)


def test_every_tag_maps_to_exactly_one_family():
    assert len(TAG_TO_FAMILY) == len(set(TAG_TO_FAMILY))
    assert len(TAG_TO_FAMILY) == len(ALL_TAGS)
    for fam in FAMILIES:
        assert fam in TAGS
        for tag in TAGS[fam]:
            assert TAG_TO_FAMILY[tag] == fam


def test_families_are_known():
    assert is_valid_family("python")
    assert is_valid_family("ml_classical")
    assert not is_valid_family("bogus")
    assert not is_valid_family("")


def test_aliases_resolve_to_canonical():
    assert normalize_tag("random_forest") == "trees_ensembles"
    assert normalize_tag("Random Forest") == "trees_ensembles"
    assert normalize_tag("self_attention") == "attention_transformer"
    assert family_of("logistic") == "ml_classical"
    assert family_of("shap") == "mlops_serving"


def test_unknown_tag_is_invalid():
    assert not is_valid_tag("quantum_computing")
    assert not is_valid_tag("")
    assert family_of("nope") is None


def test_validate_default():
    assert validate(None) == {"primary": "python", "secondary": []}


def test_validate_canonicalizes_and_dedupes():
    assert validate({"primary": "random forest", "secondary": ["pca", "pca"]}) == {
        "primary": "trees_ensembles",
        "secondary": ["dimensionality_reduction"],
    }


def test_validate_rejects_unknown_primary():
    with pytest.raises(ValueError):
        validate({"primary": "bogus"})


def test_validate_rejects_unknown_secondary():
    with pytest.raises(ValueError):
        validate({"primary": "python", "secondary": ["bogus"]})


def test_validate_limits_secondary_count():
    with pytest.raises(ValueError):
        validate({"primary": "python", "secondary": ["mlp", "cnn", "rnn_lstm"]})


def test_validate_accepts_plain_string_primary():
    assert validate("bootstrap_ci") == {"primary": "bootstrap_ci", "secondary": []}


def test_secondary_removes_primary_duplicate():
    out = validate({"primary": "mlp", "secondary": ["mlp", "cnn"]})
    assert out == {"primary": "mlp", "secondary": ["cnn"]}


def test_family_name_allowed_as_primary():
    assert validate({"primary": "python", "secondary": []}) == {
        "primary": "python",
        "secondary": [],
    }
    assert family_of("python") == "python"


def test_family_name_rejected_as_secondary():
    with pytest.raises(ValueError):
        validate({"primary": "mlp", "secondary": ["python"]})