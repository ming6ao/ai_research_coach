"""Starter-code validation: stub structure, hygiene, and language heuristics."""

from __future__ import annotations

from coach.scaffold_validation import validate_scaffold


def test_validate_scaffold_accepts_plain_stub():
    stub = "import numpy as np\n\n\ndef f(x, y):\n    # TODO: implement\n    pass\n"
    assert validate_scaffold(stub) == []


def test_validate_scaffold_rejects_implementation_body():
    stub = "def f(x):\n    # TODO: implement\n    return x + 1\n"
    problems = validate_scaffold(stub)
    assert any("implementation body" in p for p in problems)


def test_validate_scaffold_accepts_class_and_comment_free_stubs():
    # Python stubs are judged by structure, so a class scaffold and a
    # comment-free pass/.../raise body are all valid starter code.
    assert validate_scaffold("def f(x):\n    pass\n") == []
    assert validate_scaffold("def f(x):\n    ...\n") == []
    assert validate_scaffold("def f(x):\n    raise NotImplementedError\n") == []
    assert validate_scaffold("class A:\n    def f(self):\n        # TODO\n        pass\n") == []
    assert validate_scaffold("class A:\n    pass\n") == []


def test_validate_scaffold_still_rejects_implemented_class_method():
    stub = "class A:\n    def f(self):\n        # TODO\n        return 1\n"
    assert any("implementation body" in p for p in validate_scaffold(stub))


def test_validate_scaffold_rejects_leaks():
    leaky = "class A:\n    def f(self):\n        # TODO\n        self.x = 1\n        pass\n"
    assert "leaks internals" in validate_scaffold(leaky)


def test_validate_scaffold_rejects_non_python_without_signature():
    assert "no function signature" in validate_scaffold("// TODO\n", language="cpp")
    # Non-Python keeps the comment heuristic since the body cannot be parsed.
    assert "no TODO marker" in validate_scaffold(
        "int f(int x) {\n    return 0;\n}\n", language="cpp"
    )
