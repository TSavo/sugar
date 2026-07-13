"""len(xs): reduce the argument, and ask it for its length. Concrete collections
fold to TermValue(count); symbolic values stay the call:len coordinate."""

from __future__ import annotations

import ast

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import CallSiteValue, TermValue, UniverseValue
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num, py_eq
from sugar_lift_py_tests.outcome import complete_value


def _universe(source: str) -> UniverseValue:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert isinstance(value, UniverseValue)
    return value


def test_len_of_list_literal_folds() -> None:
    assert reduce_value("len([1, 2])") == TermValue(2)


def test_len_of_string_folds() -> None:
    assert reduce_value('len("abc")') == TermValue(3)


def test_len_of_symbolic_is_the_call_len_coordinate() -> None:
    value = reduce_value("len(z)", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "len"
    assert value.term == ctor("call:len", [make_var("z")])


def test_len_coordinate_joins_assert_sentences() -> None:
    universe = _universe("def A(z):\n    assert len(z) == 3\n    return z\n")
    assert universe.invs() == (py_eq(ctor("call:len", [make_var("z")]), num(3)),)


def test_len_of_number_panics_on_the_length_floor() -> None:
    with pytest.raises(FactoryPanic, match="stand on the length floor"):
        reduce_value("len(5)")


def test_len_with_two_args_stays_call_sugar() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("len(1, 2)", mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    assert result.audit_row.selected == "CallSugar"
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "len"
    assert len(value.arg_values) == 2
