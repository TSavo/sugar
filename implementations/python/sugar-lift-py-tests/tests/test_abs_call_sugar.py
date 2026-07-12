"""The vendor ``abs(value)`` folds numbers and preserves symbolic coordinates."""

from __future__ import annotations

import ast

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.outcome import complete_value


def _selected(expr: str) -> str:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(expr, mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    return result.audit_row.selected


def test_ground_abs_folds_both_signs_and_float() -> None:
    assert reduce_value("abs(-5)") == TermValue(5)
    assert reduce_value("abs(3)") == TermValue(3)
    assert reduce_value("abs(-1.5)") == TermValue(1.5)


def test_symbolic_abs_carries_its_argument_coordinate() -> None:
    x = reduce_value("abs(x)", binds={"x": SymbolicValue(make_var("x"))})
    y = reduce_value("abs(y)", binds={"y": SymbolicValue(make_var("y"))})

    assert isinstance(x, CallSiteValue)
    assert isinstance(y, CallSiteValue)
    assert x.term == ctor("call:abs", [make_var("x")])
    assert y.term == ctor("call:abs", [make_var("y")])
    assert x.term != y.term


def test_ownership_partition_is_exact() -> None:
    assert _selected("abs(x)") == "AbsCallSugar"
    assert _selected("f(x)") == "CallSugar"
    assert _selected("abs(x, y)") == "CallSugar"
    assert _selected("abs(*xs)") == "CallSugar"
    assert _selected("abs(x=x)") != "AbsCallSugar"


def test_non_owned_two_argument_abs_keeps_call_sugar_coordinate() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("abs(1, 2)", mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    value = complete_value(result.sugar.desugar(ctx), owner="test")

    assert isinstance(value, CallSiteValue)
    assert value.term == ctor(
        "call:abs",
        [
            TermValue(1).to_term(owner="test"),
            TermValue(2).to_term(owner="test"),
        ],
    )


def test_symbolic_abs_composes_inside_full_assert_comparison() -> None:
    source = "def A(z):\n    assert abs(z) <= 1.0\n    return z\n"
    payload = lift_file_payload(source, "t.py")
    assertion = next(contract for contract in payload.ir if contract.inv is not None)

    assert "call:abs" in repr(assertion.inv)
    assert "py.lt" in repr(assertion.inv)


def test_ground_abs_comparison_folds_true_in_full_assert() -> None:
    source = "def A():\n    assert abs(-3) <= 5\n    return 1\n"
    payload = lift_file_payload(source, "t.py")

    assert any(
        row.line == 2 and row.selected == "AssertSugar" and row.status == "warranted"
        for row in payload.factory_walk
    )
    assert all(contract.inv is None for contract in payload.ir)
