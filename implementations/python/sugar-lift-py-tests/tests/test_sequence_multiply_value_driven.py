from __future__ import annotations

import importlib

import pytest

from sugar_lift_py_tests.effect import TypeErrorRuntimeEffect
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ImportAliasValue,
    ListValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import _Ctor, ctor
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _site(tmp_path):
    source = tmp_path / "sequence_repeat.py"
    source.write_text("def witness():\n    return [1] * 1.5\n", encoding="utf-8")
    return next(SourceFile(path_source(str(source))).functions()).fragment


def _symbolic_result(sequence, multiplier):
    outcome = sequence.multiply(multiplier, "multiply-site")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)
    term = outcome.value.term
    assert isinstance(term, _Ctor)
    assert term.name == "python:sequence_repeat"
    return term


@pytest.mark.parametrize("sequence_type", (ListValue, TupleValue))
def test_exact_constructed_integer_is_the_only_finite_repetition_path(
    sequence_type,
) -> None:
    element = TermValue(7)

    outcome = sequence_type((element,)).multiply(TermValue(64), "multiply-site")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, sequence_type)
    assert outcome.value.elements == (element,) * 64


@pytest.mark.parametrize("sequence_type", (ListValue, TupleValue))
def test_exact_constructed_bool_is_a_valid_repetition_count(sequence_type) -> None:
    element = TermValue(7)

    outcome = sequence_type((element,)).multiply(TermValue(True), "multiply-site")

    assert isinstance(outcome, Complete)
    assert outcome.value.elements == (element,)


def test_list_times_known_ground_float_is_loud_type_error(tmp_path) -> None:
    outcome = ListValue((TermValue(1),)).multiply(TermValue(1.5), _site(tmp_path))

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, TypeErrorRuntimeEffect)


def test_tuple_times_known_ground_string_is_loud_type_error(tmp_path) -> None:
    outcome = TupleValue((TermValue(1),)).multiply(
        TermValue("x"),  # type: ignore[arg-type] - planted invalid ground payload
        _site(tmp_path),
    )

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, TypeErrorRuntimeEffect)


@pytest.mark.parametrize("sequence_type", (ListValue, TupleValue))
def test_unresolved_imported_constant_constructs_symbolic_repetition(
    sequence_type, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_import(*args, **kwargs):
        raise AssertionError(f"construction opened a module: {args!r} {kwargs!r}")

    monkeypatch.setattr(importlib, "import_module", no_import)
    assert not hasattr(ImportAliasValue, "resolve_value")
    imported = ImportAliasValue(
        "somevendor.MAXDIMS",
        "MAXDIMS",
        import_target="somevendor.MAXDIMS",
    )

    term = _symbolic_result(sequence_type((TermValue(7),)), imported)

    assert term.args[1] == imported.to_term(owner="test")


@pytest.mark.parametrize("sequence_type", (ListValue, TupleValue))
def test_bridge_coordinate_rename_changes_only_multiplier_term(sequence_type) -> None:
    sequence = sequence_type((TermValue(7),))
    first = CallSiteValue("vendor_a.op", (), (), ctor("call:vendor_a.op", []), None)
    renamed = CallSiteValue("vendor_b.op", (), (), ctor("call:vendor_b.op", []), None)

    first_term = _symbolic_result(sequence, first)
    renamed_term = _symbolic_result(sequence, renamed)

    assert first_term.name == renamed_term.name == "python:sequence_repeat"
    assert first_term.args[0] == renamed_term.args[0]
    assert first_term.args[1] == first.term
    assert renamed_term.args[1] == renamed.term


@pytest.mark.parametrize("sequence_type", (ListValue, TupleValue))
def test_nested_imported_calls_remain_nested_under_sequence_repetition(
    sequence_type,
) -> None:
    inner = CallSiteValue("vendor.inner", (), (), ctor("call:vendor.inner", []), None)
    outer = CallSiteValue(
        "vendor.outer",
        (inner,),
        (),
        ctor("call:vendor.outer", [inner.term]),
        None,
    )

    term = _symbolic_result(sequence_type((TermValue(7),)), outer)

    assert term.args[1] == outer.term
    assert isinstance(term.args[1], _Ctor)
    assert term.args[1].name == "call:vendor.outer"
    assert term.args[1].args == (inner.term,)
