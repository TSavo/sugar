from __future__ import annotations

import ast

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import ArrayLiteral, Bv32Value, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var, num, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def test_str_builtin_folds_concrete_number() -> None:
    assert fol(reduce_term("str(12)")) == fol(str_const("12"))


def test_str_builtin_symbolic_argument_emits_structural_term() -> None:
    result = reduce_term("str(x)", {"x": SymbolicValue(make_var("x"))})

    assert fol(result) == fol(ctor("py.str", [make_var("x")]))


def test_str_builtin_dispatches_bv32_argument_to_floor_operation() -> None:
    result, operation_log = _reduce_value_with_log(
        "str(x)", {"x": Bv32Value(make_var("x"))}
    )

    assert result == SymbolicValue(ctor("py.str", [make_var("x")]))
    assert operation_log == [("BuiltinCallSugar", "str_with", "StrCoercionOperation")]


def test_len_builtin_symbolic_argument_emits_structural_term() -> None:
    result = reduce_term("len(x)", {"x": SymbolicValue(make_var("x"))})

    assert fol(result) == fol(ctor("py.len", [make_var("x")]))


def test_len_builtin_symbolic_argument_is_not_concretized() -> None:
    result, operation_log = _reduce_value_with_log(
        "len(x)", {"x": SymbolicValue(make_var("x"))}
    )

    assert result == SymbolicValue(ctor("py.len", [make_var("x")]))
    assert not isinstance(result, TermValue)
    assert operation_log == [
        ("BuiltinCallSugar", "call_method_with", "MethodCallOperation")
    ]


def test_len_builtin_symbolic_argument_preserves_receiver_identity() -> None:
    left = reduce_term("len(x)", {"x": SymbolicValue(make_var("x"))})
    right = reduce_term("len(y)", {"y": SymbolicValue(make_var("y"))})

    assert fol(left) != fol(right)
    assert fol(right) == fol(ctor("py.len", [make_var("y")]))


def test_len_builtin_array_literal_still_folds_concrete_length() -> None:
    result = reduce_term("len(xs)", {"xs": ArrayLiteral((TermValue(1), TermValue(2)))})

    assert fol(result) == fol(num(2))


def _reduce_value_with_log(expr: str, binds: dict | None = None):
    temporal = TemporalContext.empty()
    for name, value in (binds or {}).items():
        temporal = temporal.bind_value(name, value)
    build_ctx = FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        temporal=temporal,
    )
    node = ast.parse(expr, mode="eval").body
    body = build_ctx.build_body(node, SugarRole.TERM)
    reduce_ctx = ReduceContext(temporal=temporal)
    return (
        complete_value(body.reduce(reduce_ctx), owner="builtin call test"),
        reduce_ctx.operation_log,
    )
