from __future__ import annotations


import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ListValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import _Ctor, ctor
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect import RaiseEffect


def _site(tmp_path):
    """Workspace-relative fragment so ground TypeError can cite source."""
    del tmp_path
    source = "def witness():\n    return [1] * 1.5\n"
    tree = SourceFile(
        (source, "sequence_repeat.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(tree.functions()).fragment


def _symbolic_result(sequence, multiplier):
    outcome = sequence.multiply(multiplier, "multiply-site", None)
    value = outcome.completed_value()
    assert isinstance(value, SymbolicValue)
    term = value.term
    assert isinstance(term, _Ctor)
    assert term.name == "python:sequence_repeat"
    return term


@pytest.mark.parametrize("sequence_type", (ListValue, TupleValue))
def test_exact_constructed_integer_is_the_only_finite_repetition_path(
    sequence_type,
) -> None:
    element = TermValue(7)

    outcome = fresh(sequence_type, (element,)).multiply(
        TermValue(64), "multiply-site", None
    )

    value = outcome.completed_value()
    assert isinstance(value, sequence_type)
    assert value.elements == (element,) * 64


@pytest.mark.parametrize("sequence_type", (ListValue, TupleValue))
def test_exact_constructed_bool_is_a_valid_repetition_count(sequence_type) -> None:
    element = TermValue(7)

    outcome = fresh(sequence_type, (element,)).multiply(
        TermValue(True), "multiply-site", None
    )

    value = outcome.completed_value()
    assert value is not None
    assert value.elements == (element,)


def test_list_times_known_ground_float_is_authenticated_type_error(tmp_path) -> None:
    outcome = fresh(ListValue, (TermValue(1),)).multiply(
        TermValue(1.5), _site(tmp_path), None
    )

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "TypeError"


def test_tuple_times_known_ground_string_is_authenticated_type_error(tmp_path) -> None:
    outcome = TupleValue((TermValue(1),)).multiply(
        TermValue("x"),  # type: ignore[arg-type] - planted invalid ground payload
        _site(tmp_path),
        None,
    )

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "TypeError"


@pytest.mark.parametrize("sequence_type", (ListValue, TupleValue))
def test_bridge_coordinate_rename_changes_only_multiplier_term(sequence_type) -> None:
    sequence = fresh(sequence_type, (TermValue(7),))
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

    term = _symbolic_result(fresh(sequence_type, (TermValue(7),)), outer)

    assert term.args[1] == outer.term
    assert isinstance(term.args[1], _Ctor)
    assert term.args[1].name == "call:vendor.outer"
    assert term.args[1].args == (inner.term,)
