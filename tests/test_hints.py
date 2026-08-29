"""Unit tests for adaptive hint selection in core.hints."""

import pytest

from core.hints import hint_penalty, next_hidden_hint, select_hints

TASK = {
    "id": "t1",
    "hints": [
        {"id": "h1", "text": "gentle", "weight": 0.1, "reveal_threshold": 0.6},
        {"id": "h2", "text": "strong", "weight": 0.25, "reveal_threshold": 0.4},
        {"id": "h3", "text": "always-hidden", "weight": 0.2},
    ],
}


def test_select_hints_pre_reveals_below_threshold():
    selected = select_hints(TASK, ability_mean=0.3)
    by_id = {h["id"]: h["pre_revealed"] for h in selected}
    assert by_id == {"h1": True, "h2": True, "h3": False}


def test_select_hints_keeps_hidden_for_strong_ability():
    selected = select_hints(TASK, ability_mean=0.7)
    by_id = {h["id"]: h["pre_revealed"] for h in selected}
    assert by_id == {"h1": False, "h2": False, "h3": False}


def test_select_hints_partial_reveal():
    selected = select_hints(TASK, ability_mean=0.5)
    by_id = {h["id"]: h["pre_revealed"] for h in selected}
    assert by_id == {"h1": True, "h2": False, "h3": False}


def test_select_hints_carries_id_text_weight():
    selected = select_hints(TASK, ability_mean=0.5)
    assert selected[0]["id"] == "h1"
    assert selected[0]["text"] == "gentle"
    assert selected[0]["weight"] == pytest.approx(0.1)


def test_select_hints_defaults_weight():
    task = {"id": "t", "hints": [{"id": "a", "text": "x"}]}
    selected = select_hints(task, ability_mean=0.0)
    assert selected[0]["weight"] == pytest.approx(0.15)


def test_hint_penalty_only_counts_viewed():
    assert hint_penalty(TASK, []) == 0.0
    assert hint_penalty(TASK, ["h1"]) == pytest.approx(0.1)
    assert hint_penalty(TASK, ["h1", "h2"]) == pytest.approx(0.35)


def test_hint_penalty_ignores_unknown_ids():
    assert hint_penalty(TASK, ["h1", "nope"]) == pytest.approx(0.1)


def test_next_hidden_hint_returns_first_unviewed():
    assert next_hidden_hint(TASK, [])["id"] == "h1"
    assert next_hidden_hint(TASK, ["h1", "h2"])["id"] == "h3"


def test_next_hidden_hint_skips_pre_revealed():
    # At ability 0.5, h1 (threshold 0.6) is pre-revealed, so the first
    # requestable hint is h2.
    assert next_hidden_hint(TASK, [], ability_mean=0.5)["id"] == "h2"
    assert next_hidden_hint(TASK, ["h2"], ability_mean=0.5)["id"] == "h3"


def test_next_hidden_hint_none_when_all_viewed():
    assert next_hidden_hint(TASK, ["h1", "h2", "h3"]) is None
    # At a low ability every thresholded hint is pre-revealed, so only the
    # threshold-less (always requestable) hint remains.
    assert next_hidden_hint(TASK, [], ability_mean=0.1)["id"] == "h3"


def test_select_hints_empty_when_no_hints():
    assert select_hints({"id": "t", "prompt": "x"}, 0.0) == []