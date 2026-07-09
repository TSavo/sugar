from __future__ import annotations

import ast

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    Bv32Value,
    OpaqueOpCallsite,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def test_str_builtin_concrete_number_is_coordinate_carrying_folded_string() -> None:
    # str(12) is call:str(12) carrying computed "12" — never bare "12".
    value, _log = _reduce_value_with_log("str(12)")

    assert isinstance(value, OpaqueOpCallsite)
    assert value.callee == "str"
    assert value.computed == StringValue("12")
    assert fol(reduce_term("str(12)")) == fol(ctor("call:str", [num(12)]))


def test_str_builtin_symbolic_argument_emits_call_coordinate() -> None:
    result = reduce_term("str(x)", {"x": SymbolicValue(make_var("x"))})

    assert fol(result) == fol(ctor("call:str", [make_var("x")]))


def test_str_builtin_dispatches_bv32_argument_to_floor_operation() -> None:
    result, operation_log = _reduce_value_with_log(
        "str(x)", {"x": Bv32Value(make_var("x"))}
    )

    assert result == OpaqueOpCallsite(
        callee="str", arg=Bv32Value(make_var("x")), computed=None
    )
    assert operation_log == [("BuiltinCallSugar", "str_with", "StrCoercionOperation")]


def test_len_builtin_symbolic_argument_emits_call_coordinate() -> None:
    # `len(x)` over an opaque argument is the callsite coordinate `call:len(x)` --
    # the SAME symbol the LHS/assertion surface emits -- not a `py.len` variant that
    # could never join it by congruence.
    result = reduce_term("len(x)", {"x": SymbolicValue(make_var("x"))})

    assert fol(result) == fol(ctor("call:len", [make_var("x")]))


def test_len_builtin_symbolic_argument_is_not_concretized() -> None:
    result, operation_log = _reduce_value_with_log(
        "len(x)", {"x": SymbolicValue(make_var("x"))}
    )

    assert result == OpaqueOpCallsite(
        callee="len", arg=SymbolicValue(make_var("x")), computed=None
    )
    assert not isinstance(result, TermValue)
    assert operation_log == [
        ("BuiltinCallSugar", "call_method_with", "MethodCallOperation")
    ]


def test_len_builtin_symbolic_argument_preserves_receiver_identity() -> None:
    left = reduce_term("len(x)", {"x": SymbolicValue(make_var("x"))})
    right = reduce_term("len(y)", {"y": SymbolicValue(make_var("y"))})

    assert fol(left) != fol(right)
    assert fol(right) == fol(ctor("call:len", [make_var("y")]))


def test_len_builtin_array_literal_is_coordinate_carrying_counted_length() -> None:
    # `len([1,2])` is the opaque coordinate `call:len(array(1,2))` carrying the
    # counted value 2 in `computed` -- NOT the bare scalar. The coordinate is what
    # the term projects to; the count rides along so the emission layer can emit the
    # derived companion `call:len(array(1,2)) == 2` (grounding by transitivity),
    # never collapsing the coordinate.
    value, _log = _reduce_value_with_log(
        "len(xs)", {"xs": ArrayLiteral((TermValue(1), TermValue(2)))}
    )

    assert isinstance(value, OpaqueOpCallsite)
    assert value.callee == "len"
    assert value.computed == TermValue(2)

    # The projected term is the coordinate, never the bare scalar.
    term = reduce_term("len(xs)", {"xs": ArrayLiteral((TermValue(1), TermValue(2)))})
    assert fol(term) == fol(ctor("call:len", [ctor("array", [num(1), num(2)])]))


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
