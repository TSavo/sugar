"""BinOpSugar folds a concrete `+` (via Python, the reference); a SYMBOLIC `+` EMITS the
operation as a sort-silent structural term `+(x, 1)` -- the universe warrant. We emit the
SHAPE, not a value; the SMT compiler derives x's carrier from the `+` it appears in. Never a
mislift, never folding what cannot be folded."""

from __future__ import annotations

import ast

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    Bv32Value,
    EncodedStringValue,
    StringValue,
    SymbolicValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def _temporal(binds: dict | None = None) -> TemporalContext:
    temporal = TemporalContext.empty()
    for name, value in (binds or {}).items():
        temporal = temporal.bind_value(name, value)
    return temporal


def _reduce_outcome_with_log(expr: str, binds: dict | None = None):
    temporal = _temporal(binds)
    build_ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = build_ctx.build_body(ast.parse(expr, mode="eval").body, SugarRole.TERM)
    reduce_ctx = ReduceContext(temporal=temporal)
    return body.reduce(reduce_ctx), reduce_ctx.operation_log


def _reduce_with_log(expr: str, binds: dict | None = None):
    outcome, operation_log = _reduce_outcome_with_log(expr, binds)
    value = complete_value(outcome, owner="binop dispatch test")
    return value, operation_log


def test_add_folds_concrete_literals():
    assert fol(reduce_term("2 + 3")) == fol(num(5))


def test_division_by_zero_stays_runtime_effect():
    outcome, operation_log = _reduce_outcome_with_log("1 // 0")

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "RuntimeEffect"
    assert "division by zero" in outcome.reason
    assert operation_log == [
        ("BinOpSugar", "binary_operator_with", "BinaryOperatorOperation")
    ]


def test_binop_dispatches_through_floor_operation_log():
    value, operation_log = _reduce_with_log("2 + 3")

    assert value.value == 5
    assert operation_log == [
        ("BinOpSugar", "binary_operator_with", "BinaryOperatorOperation")
    ]


def test_expanded_numeric_binary_stays_on_binary_operator_floor():
    value, operation_log = _reduce_with_log("8 // 3")

    assert value.value == 2
    assert operation_log == [
        ("BinOpSugar", "binary_operator_with", "BinaryOperatorOperation")
    ]


def test_encoded_string_concat_dispatches_through_left_floor():
    value, operation_log = _reduce_with_log(
        "tbl[i] + tbl[j]",
        {
            "tbl": StringValue("ABCD"),
            "i": Bv32Value(make_var("i")),
            "j": Bv32Value(make_var("j")),
        },
    )

    assert value == EncodedStringValue(
        table=(65, 66, 67, 68), indices=(make_var("i"), make_var("j"))
    )
    assert operation_log[-1] == (
        "BinOpSugar",
        "binary_operator_with",
        "BinaryOperatorOperation",
    )


def test_add_on_symbolic_operand_emits_the_operation_sort_silent():
    # A free var is irreducible, so the `+` cannot fold to a value -- but it is not a panic.
    # BinOpSugar emits the operation `+(x, 1)` (the structural term the universe walk warrants).
    result = reduce_term("x + 1", {"x": SymbolicValue(make_var("x"))})
    assert fol(result) == fol(ctor("+", [make_var("x"), num(1)]))


def test_tuple_multiplication_repeats_literal_tuple():
    assert fol(reduce_term("(1,) * 3")) == fol(ctor("tuple", [num(1), num(1), num(1)]))


def test_list_multiplication_repeats_literal_array():
    assert fol(reduce_term("[1] * 3")) == fol(ctor("array", [num(1), num(1), num(1)]))


def test_reversed_sequence_multiplication_repeats_literal_sequence():
    assert fol(reduce_term("3 * (1,)")) == fol(ctor("tuple", [num(1), num(1), num(1)]))
    assert fol(reduce_term("3 * [1]")) == fol(ctor("array", [num(1), num(1), num(1)]))
