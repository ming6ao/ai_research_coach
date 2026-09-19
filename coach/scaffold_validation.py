"""Validate LLM-proposed step starter code (``scaffold``).

A step's scaffold is the stub a learner sees before attempting it. It must
parse and must not give the answer away: no implementation bodies, no leaked
instance state, no invalid syntax. ``TaskDecomposer._assemble_draft`` (reached
via ``POST /api/v1/tasks/draft``) rejects and retries any stub that fails
``validate_scaffold``.

Python stubs are judged structurally, so a class scaffold and a comment-free
``pass``/``...``/``raise NotImplementedError`` body are all accepted. Other
languages have no AST here, so they fall back to a comment-marker and a
function-signature heuristic.
"""

from __future__ import annotations

import ast
import re

MAX_SCAFFOLD_CHARS = 16000

# Starter code must not declare private members or instance state.
_HYGIENE_PRIVATE = re.compile(r"(^|\n)\s*(private|protected)\s*:")
_HYGIENE_MEMBER = re.compile(r"(^|\n)\s*(?:mutable\s+)?[\w:<>,\s*&]+\s+\w+_\s*(?:=|;)")
_HYGIENE_SELF = re.compile(r"(^|\n)\s*self\.\w+\s*=")
_TODO_MARK = re.compile(r"#|//|/\*")


def validate_scaffold(scaffold: str, *, language: str = "python") -> list[str]:
    """Return a list of reasons the stub is unusable / answer-revealing.

    Not unhelpful-but-valid: a Python stub is accepted whenever it parses and
    every function/method body is a stub (a bare ``pass``/``...``/``raise
    NotImplementedError`` or docstring), including class scaffolds. Only
    non-Python stubs rely on the ``# TODO`` heuristic, since their bodies
    cannot be parsed.
    """
    problems: list[str] = []
    text = (scaffold or "").strip()
    if not text:
        return ["empty"]
    if len(text) > MAX_SCAFFOLD_CHARS:
        problems.append("too long")
    if (
        _HYGIENE_PRIVATE.search(text)
        or _HYGIENE_MEMBER.search(text)
        or _HYGIENE_SELF.search(text)
    ):
        problems.append("leaks internals")
    if language == "python":
        problems.extend(_validate_python_stub(text))
    else:
        # No AST for other languages: fall back to heuristic markers.
        if not _TODO_MARK.search(text):
            problems.append("no TODO marker")
        if not re.search(r"[A-Za-z_]\w*\s+\w+\s*\(", text):
            problems.append("no function signature")
    return problems


def _iter_functions(nodes) -> list:
    """Every function/method declared under these AST nodes, in source order."""
    out = []
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
        elif isinstance(node, ast.ClassDef):
            out.extend(_iter_functions(node.body))
    return out


def _validate_python_stub(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [f"invalid Python syntax: {exc.msg}"]
    definitions = [
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if not definitions:
        return ["no function or class definition"]
    problems: list[str] = []
    for node in tree.body:
        if isinstance(
            node,
            (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # module docstring
        problems.append("unexpected top-level statement")
        break
    # A class scaffold is valid: check its methods (and any nested functions)
    # have stub bodies, not just the top-level functions.
    for fn in _iter_functions(definitions):
        if not _is_stub_body(fn.body):
            problems.append(f"{fn.name} has an implementation body")
    return problems


def _is_stub_body(body: list) -> bool:
    """True when a function body only comments/docstrings/pass/NotImplemented."""
    for node in body:
        if isinstance(node, ast.Pass):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.Raise):
            exc = node.exc
            if isinstance(exc, ast.Call):
                exc = exc.func
            if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
                continue
        return False
    return True
