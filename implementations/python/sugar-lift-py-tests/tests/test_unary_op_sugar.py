from __future__ import annotations

import ast

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def _reduce_with_log(expr: str):
    build_ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = build_ctx.build_body(ast.parse(expr, mode="eval").body, SugarRole.TERM)
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())
    value = complete_value(body.reduce(reduce_ctx), owner="unary dispatch test")
    return value, reduce_ctx.operation_log


def test_unary_minus_folds_concrete_number() -> None:
    assert fol(reduce_term("-3")) == fol(num(-3))


def test_unary_plus_folds_concrete_number() -> None:
    assert fol(reduce_term("+3")) == fol(num(3))


def test_unary_op_dispatches_through_floor_operation_log() -> None:
    value, operation_log = _reduce_with_log("-3")

    assert value.value == -3
    assert operation_log == [
        ("UnaryOpSugar", "unary_operator_with", "UnaryOperatorOperation")
    ]


def test_unary_minus_symbolic_operand_emits_structural_term() -> None:
    result = reduce_term("-x", {"x": SymbolicValue(make_var("x"))})

    assert fol(result) == fol(ctor("py.neg", [make_var("x")]))


def test_unary_plus_symbolic_operand_returns_operand() -> None:
    result = reduce_term("+x", {"x": SymbolicValue(make_var("x"))})

    assert fol(result) == fol(make_var("x"))
