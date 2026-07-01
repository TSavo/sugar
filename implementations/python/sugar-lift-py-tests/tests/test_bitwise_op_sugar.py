"""BitwiseOpSugar reduces Python bit operators to the canonical bv32 ctors."""

from __future__ import annotations

import ast

import pytest

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import Bv32Value
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def _x():
    return {"x": Bv32Value(make_var("x"))}


def test_bitwise_and_reduces_to_bv32_and():
    assert fol(reduce_term("x & 15", _x())) == fol(
        ctor("bv32.and", [make_var("x"), num(15)])
    )


def test_bitwise_rshift_reduces_to_bv32_lshr():
    assert fol(reduce_term("x >> 2", _x())) == fol(
        ctor("bv32.lshr", [make_var("x"), num(2)])
    )


def test_bitwise_or_dispatches_bv32_receiver_to_floor_operation():
    result, operation_log = _reduce_value_with_log("x | 3", _x())

    assert result == Bv32Value(ctor("bv32.or", [make_var("x"), num(3)]))
    assert operation_log == [("BitwiseOpSugar", "bitwise_with", "BitwiseOperation")]


def test_bitwise_lshift_dispatches_term_receiver_without_python_solving():
    result, operation_log = _reduce_value_with_log("1 << x", _x())

    assert result == Bv32Value(ctor("bv32.shl", [num(1), make_var("x")]))
    assert operation_log == [("BitwiseOpSugar", "bitwise_with", "BitwiseOperation")]


def test_bitwise_missing_receiver_capability_is_a_named_floor_gap():
    with pytest.raises(FactoryGap) as raised:
        _reduce_value_with_log("'bad' & 1")

    assert raised.value.info == {
        "owner": "BitwiseOpSugar",
        "blame": "t.py:1:0",
        "observed": "StringValue",
        "requested": "bitwise_with",
        "fix": "add bitwise_with to StringValue or emit a real effect",
    }


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
        complete_value(body.reduce(reduce_ctx), owner="bitwise test"),
        reduce_ctx.operation_log,
    )
