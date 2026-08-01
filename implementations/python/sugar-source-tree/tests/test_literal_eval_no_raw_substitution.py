"""literal_eval failure must throw — never substitute raw source as value.

SIN CLUSTER 4 / coord 4 — parso_adapter (and the tree-sitter twin) caught
``literal_eval`` failure and set ``Constant.value`` to the raw source text.
That is meaning produced outside Sugar (LAW_OF_ONE).

DELETE the fallback. Decode or throw. No backend_defect wrapper, no catch.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def test_truthful_literal_eval_failure_propagates():
    """Truthful twin: undecodable text raises from literal_eval — no value."""
    text = r"'\x'"
    with pytest.raises((ValueError, SyntaxError)):
        ast.literal_eval(text)


def test_lying_raw_source_substitution_is_the_crime():
    """Lying twin: except → value = text launders a parse failure into data."""
    text = r"'\x'"
    try:
        value = ast.literal_eval(text)
        pytest.fail(f"expected literal_eval to fail, got {value!r}")
    except Exception:
        lying_value = text  # the sin: raw source as Constant.value

    assert lying_value == text
    assert isinstance(lying_value, str)
    # Truthful: the exception stands; no Constant.value is minted from it.
    with pytest.raises((ValueError, SyntaxError)):
        ast.literal_eval(text)


def test_parso_adapter_source_has_no_literal_eval_fallback():
    """Static twin: production parso adapter does not catch-and-substitute."""
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_source_tree"
        / "parso_adapter.py"
    ).read_text(encoding="utf-8")
    assert "value = _pyast.literal_eval(text)" in source
    assert "value = text" not in source
    assert "value = unit.source[start:end]" not in source
    # No catch wrapping literal_eval into a survival path (named or silent).
    assert "except Exception" not in source or not _literal_eval_has_except(source)


def test_tree_sitter_adapter_source_has_no_literal_eval_fallback():
    """Same law for the tree-sitter twin adapter."""
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_source_tree"
        / "tree_sitter_python_adapter.py"
    ).read_text(encoding="utf-8")
    assert "value = _pyast.literal_eval(text)" in source
    assert "value = text" not in source
    assert "value = unit.source[span.start : span.end]" not in source
    assert "except Exception" not in source or not _literal_eval_has_except(source)


def _literal_eval_has_except(source: str) -> bool:
    """True if any literal_eval call sits under an except-surviving handler."""
    import ast as py_ast

    tree = py_ast.parse(source)
    for node in py_ast.walk(tree):
        if not isinstance(node, py_ast.Try):
            continue
        for child in py_ast.walk(node):
            if (
                isinstance(child, py_ast.Call)
                and isinstance(child.func, py_ast.Attribute)
                and child.func.attr == "literal_eval"
            ):
                return True
    return False
