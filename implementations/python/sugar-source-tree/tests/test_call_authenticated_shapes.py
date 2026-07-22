"""Authenticated non-lambda call-shape discrimination for the pandas Call lane."""

from __future__ import annotations

import tempfile

import pytest

from sugar_lift_py_tests.ir import constructor_symbol_kinds, term_intern_scope
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.tree_enumerate import (
    find_function_by_name,
    function_contract_rows,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _source_file(source: str) -> SourceFile:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return SourceFile(path_source(path))


def _returned_term(source: str):
    return _function(source).sugar().desugar().value.post().args[1]


def test_shadowed_builtin_name_does_not_acquire_builtin_semantics() -> None:
    with term_intern_scope():
        function = _function("def A(len, x):\n    return len(x)\n")
        function.sugar().desugar()

        assert constructor_symbol_kinds()["call:len"] == "coordinate"


def test_same_spelled_callees_keep_distinct_source_contract_coordinates() -> None:
    left = _source_file("def enrolled(x):\n    return x\n")
    right = _source_file("def enrolled(x):\n    return x + 1\n")

    left_fn = find_function_by_name(left, "enrolled")
    right_fn = find_function_by_name(right, "enrolled")
    left_memento, _ = function_contract_rows(left_fn, "left.py")
    right_memento, _ = function_contract_rows(right_fn, "right.py")

    assert left_memento.source_cid != right_memento.source_cid


def test_keyword_names_and_source_order_are_preserved() -> None:
    term = _returned_term(
        "def A(x):\n    return f(x, second=2, first=1)\n"
    )

    assert term.name == "call:f"
    assert [arg.name for arg in term.args[1:]] == ["py.kwarg", "py.kwarg"]
    assert [arg.args[0].value for arg in term.args[1:]] == ["second", "first"]
    assert [arg.args[1].value for arg in term.args[1:]] == [2, 1]


def test_keyword_spread_is_not_silently_dropped() -> None:
    with pytest.raises(SugarNotWritten):
        _function("def A(x, d):\n    return f(x, **d)\n").sugar()


def test_computed_callee_preserves_its_own_constructed_term() -> None:
    term = _returned_term("def A(fs, i, x):\n    return fs[i](x)\n")

    assert term.name == "py.call"
    assert term.args[0].name == "py.subscript"
    assert [arg.name for arg in term.args[0].args] == ["fs", "i"]


def test_computed_callee_with_keyword_remains_loud() -> None:
    with pytest.raises(SugarNotWritten):
        _function("def A(fs, i, x):\n    return fs[i](value=x)\n").sugar()


def test_inline_lambda_call_remains_deferred_to_lambda_lane() -> None:
    with pytest.raises(SugarNotWritten):
        _function("def A(x):\n    return (lambda value: value)(x)\n").sugar()


def test_named_call_is_a_dig_cue_with_truthful_and_lying_contract_twins() -> None:
    function = _function("def A(x):\n    return enrolled(x)\n")
    call_value = function.body[0].value.sugar().desugar().value
    witness = CallSiteSugar.witnesses()

    assert call_value.term.name == "call:enrolled"
    assert call_value.body is None
    assert witness.truthful.expected == "sat"
    assert witness.lying.expected == "unsat"
    assert "assert A(5) == 5" in witness.truthful.source
    assert "assert A(5) == 6" in witness.lying.source
