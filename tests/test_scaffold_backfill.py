"""Starter-code backfill: deterministic recovery, stub validation, annotation."""

from __future__ import annotations

from coach.scaffold_backfill import (
    annotate_prompt,
    plan_recover,
    split_scaffold,
    validate_scaffold,
)


TOP_LEVEL = """\
import numpy as np


def conv2d_single(x, kernel, padding=0, stride=1):
    # TODO: return output matrix
    pass


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def lstm_cell(x, h_prev, c_prev, W, U, b):
    # TODO: return (h_new, c_new)
    pass
"""


def _task(parts, scaffold=None):
    return {"id": "t", "language": "python", "scaffold": scaffold, "parts": parts}


def test_split_scaffold_keeps_helpers_with_next_step():
    chunks, leftover = split_scaffold(TOP_LEVEL)
    assert leftover == []
    assert len(chunks) == 3
    # The non-step ``sigmoid`` helper rides along with the next step, not the
    # previous one, and the numpy import stays with the first step.
    assert chunks[0].startswith("import numpy as np")
    assert "def conv2d_single" in chunks[0] and "sigmoid" not in chunks[0]
    assert chunks[1].startswith("def sigmoid")
    assert chunks[2].startswith("def lstm_cell")


def test_plan_recover_matches_by_step_key():
    parts = [
        {"key": "conv2d_single", "prompt": "p1"},
        {"key": "lstm_cell", "prompt": "p2"},
    ]
    plan, report = plan_recover([_task(parts, TOP_LEVEL)])
    assert list(plan) == ["t"]
    recovered = {p["key"]: p["scaffold"] for p in plan["t"]}
    assert recovered["conv2d_single"].startswith("import numpy as np")
    # ``sigmoid`` is carried into the step that follows it.
    assert "def sigmoid" in recovered["lstm_cell"]
    assert "# TODO: return (h_new, c_new)" in recovered["lstm_cell"]
    assert report[0]["status"] == "recover"


def test_plan_recover_skips_unknown_or_unmatched():
    parts = [{"key": "conv2d_single", "prompt": "p1"}]
    # Two step chunks but only one step -> refuse to guess.
    plan, report = plan_recover([_task(parts, TOP_LEVEL)])
    assert plan == {}
    assert report[0]["status"] == "skip"


def test_plan_recover_keeps_authored_scaffold_without_force():
    parts = [
        {"key": "conv2d_single", "prompt": "p1", "scaffold": "authored"},
        {"key": "lstm_cell", "prompt": "p2"},
    ]
    plan, report = plan_recover([_task(parts, TOP_LEVEL)])
    recovered = {p["key"]: p["scaffold"] for p in plan["t"]}
    assert recovered["conv2d_single"] == "authored"
    assert "# TODO: return (h_new, c_new)" in recovered["lstm_cell"]


def test_validate_scaffold_accepts_plain_stub():
    stub = "import numpy as np\n\n\ndef f(x, y):\n    # TODO: implement\n    pass\n"
    assert validate_scaffold(stub) == []


def test_validate_scaffold_rejects_implementation_body():
    stub = "def f(x):\n    # TODO: implement\n    return x + 1\n"
    problems = validate_scaffold(stub)
    assert any("implementation body" in p for p in problems)


def test_validate_scaffold_rejects_missing_todo_and_leaks():
    assert "no TODO marker" in validate_scaffold("def f(x):\n    pass\n")
    leaky = "class A:\n    def f(self):\n        # TODO\n        self.x = 1\n        pass\n"
    assert "leaks internals" in validate_scaffold(leaky)


def test_validate_scaffold_rejects_non_python_without_signature():
    assert "no function signature" in validate_scaffold("// TODO\n", language="cpp")


def test_annotate_prompt_is_idempotent():
    sig = "def zero_optimizer_step(grads, m, v, t, lr=1e-3)"
    out = annotate_prompt("Implement a ZeRO-1 Adam step.", sig)
    assert out.endswith(f"Entry point: `{sig}`")
    assert annotate_prompt(out, sig) == out
    # A prompt that already names the entry point is left alone.
    assert annotate_prompt("Implement `zero_optimizer_step(grads)`.", sig).count("Entry point") == 0
