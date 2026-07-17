"""BinOpSugar folds a concrete `+` (via Python, the reference); a SYMBOLIC `+` EMITS the
operation as a sort-silent structural term `+(x, 1)` -- the universe warrant. We emit the
SHAPE, not a value; the SMT compiler derives x's carrier from the `+` it appears in. Never a
mislift, never folding what cannot be folded."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import FactoryPanic, GapKind, GapLocus
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    Bv32Value,
    CallSiteValue,
    EncodedStringValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import ctor, make_var, num, str_const
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


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


def test_ground_floor_division_by_zero_stays_loud():
    with pytest.raises(
        FactoryPanic,
        match="construct exact floor-division-by-zero exception",
    ):
        _reduce_outcome_with_log("1 // 0")


def test_term_floor_division_constructs_symbolic_divisor_coordinate():
    outcome = TermValue(8).floor_divide(
        SymbolicValue(make_var("divisor")),
        "floor.py:1",
    )

    assert fol(outcome.value.term) == fol(ctor("//", [num(8), make_var("divisor")]))


def test_term_floor_division_constructs_callsite_divisor_coordinate():
    divisor = CallSiteValue(
        "opaque",
        (),
        (),
        ctor("call:opaque", []),
        None,
    )

    outcome = TermValue(8).floor_divide(divisor, "floor.py:1")

    assert fol(outcome.value.term) == fol(ctor("//", [num(8), ctor("call:opaque", [])]))


def test_term_floor_division_rejects_ground_non_numeric_wrong_twin():
    with pytest.raises(FactoryPanic, match="owner=floor_divide"):
        TermValue(8).floor_divide(StringValue("divisor"), "floor.py:1")


def test_term_floor_division_conserves_symbolic_assertion_without_effect():
    source = "def test_a(divisor):\n    assert 8 // divisor == 8 // divisor\n"

    payload, gaps = audit_lift_file(source, "floor_divide.py")
    rpc = payload.to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file="floor_divide.py"), rpc
    ).to_json()["assertions"]

    assert gaps == []
    assert rpc["effects"] == []
    assert assertions["stated"] == 1
    assert assertions["lifted_cited"] == 1
    assert assertions["silently_unaccounted"] == 0


def test_term_floor_division_truthful_and_lying_twins_refute(tmp_path):
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        "def test_a(divisor):\n"
        "    assert (8 // divisor == 8 // divisor)"
        " & (divisor == 1) & (divisor == 1)\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        "def test_a(divisor):\n"
        "    assert (8 // divisor == 8 // divisor)"
        " & (divisor == 1) & (not (divisor == 1))\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "FloorDivideOpSugar" in truthful.selected_sugars
    assert "FloorDivideOpSugar" in lying.selected_sugars


def test_binop_dispatches_through_floor_operation_log():
    value, operation_log = _reduce_with_log("2 + 3")

    assert value.value == 5
    assert operation_log == []


def test_expanded_numeric_binary_stays_on_binary_operator_floor():
    value, operation_log = _reduce_with_log("8 // 3")

    assert value.value == 2
    assert operation_log == []


def test_encoded_string_concat_dispatches_through_left_floor():
    value, operation_log = _reduce_with_log(
        "tbl[i] + tbl[j]",
        {
            "tbl": StringValue("ABCD"),
            "i": Bv32Value(make_var("i")),
            "j": Bv32Value(make_var("j")),
        },
    )

    assert isinstance(value, SymbolicValue)
    assert fol(value.term) == fol(
        ctor(
            "+",
            [
                ctor("py.subscript", [str_const("ABCD"), make_var("i")]),
                ctor("py.subscript", [str_const("ABCD"), make_var("j")]),
            ],
        )
    )
    assert operation_log == []


def test_add_on_symbolic_operand_emits_the_operation_sort_silent():
    # A free var is irreducible, so the `+` cannot fold to a value -- but it is not a panic.
    # BinOpSugar emits the operation `+(x, 1)` (the structural term the universe walk warrants).
    result = reduce_term("x + 1", {"x": SymbolicValue(make_var("x"))})
    assert fol(result) == fol(ctor("+", [make_var("x"), num(1)]))


def test_symbolic_string_equality_emits_predicate_value():
    value, operation_log = _reduce_with_log(
        'casting == "unsafe"',
        {"casting": SymbolicValue(make_var("casting"))},
    )

    assert value.formula.name == "py.eq"
    assert [fol(arg) for arg in value.formula.args] == [
        fol(make_var("casting")),
        fol(str_const("unsafe")),
    ]
    assert operation_log == []


def test_symbolic_binary_with_float_operand_is_typed_floor_effect():
    outcome, operation_log = _reduce_outcome_with_log(
        "x + 1.5",
        {"x": SymbolicValue(make_var("x"))},
    )

    value = complete_value(outcome, owner="symbolic real addition")
    assert isinstance(value, SymbolicValue)
    assert fol(value.term) == fol(ctor("+", [make_var("x"), value.term.args[1]]))
    assert value.term.args[1].value == "1.5"
    assert operation_log == []


def test_tuple_multiplication_repeats_literal_tuple():
    assert fol(reduce_term("(1,) * 3")) == fol(ctor("tuple", [num(1), num(1), num(1)]))


def test_list_multiplication_repeats_literal_array():
    assert fol(reduce_term("[1] * 3")) == fol(ctor("array", [num(1), num(1), num(1)]))


def test_reversed_sequence_multiplication_repeats_literal_sequence():
    assert fol(reduce_term("3 * (1,)")) == fol(ctor("tuple", [num(1), num(1), num(1)]))
    assert fol(reduce_term("3 * [1]")) == fol(ctor("array", [num(1), num(1), num(1)]))


def test_large_ground_list_repetition_is_compact_construction():
    outcome, operation_log = _reduce_outcome_with_log("[1] * 65521")

    value = complete_value(outcome, owner="large ground list repetition")
    assert fol(value.to_term(owner="test")) == fol(
        ctor("*", [ctor("array", [num(1)]), num(65521)])
    )
    assert complete_value(value.length("t.py:1:0"), owner="repetition length") == (
        TermValue(65521)
    )
    assert operation_log == []


def test_test_loc_ground_sequence_repeat_100000_constructs_not_runtime_effect():
    """#4922 ledger fingerprint: py.sequence_repeat operand=TermValue(100000).

    pandas/tests/indexing/test_loc.py:1064 binds ``l2=100000`` via literal
    parametrize into ``index=[0] * l2``. Ground counts construct a compact
    floor value; they must not mint SequenceRepetitionRuntimeEffect.
    """
    from sugar_lift_py_tests.floor.ground_sequence_repetition_value import (
        GroundSequenceRepetitionValue,
    )

    site = "pandas/tests/indexing/test_loc.py:1064:61"
    # Literal ground count (decidable at lift).
    outcome, operation_log = _reduce_outcome_with_log("[0] * 100000")
    value = complete_value(outcome, owner="test_loc ground sequence_repeat")
    assert isinstance(value, GroundSequenceRepetitionValue)
    assert value.repetitions == 100000
    assert complete_value(value.length(site), owner="test_loc length") == TermValue(
        100000
    )
    assert operation_log == []

    # Parametrize-bound name reduces to the same ground TermValue(100000).
    bound, bound_log = _reduce_outcome_with_log(
        "[0] * l2",
        {"l2": TermValue(100000)},
    )
    bound_value = complete_value(bound, owner="test_loc parametrize l2=100000")
    assert isinstance(bound_value, GroundSequenceRepetitionValue)
    assert bound_value.repetitions == 100000
    assert complete_value(bound_value.length(site), owner="bound length") == TermValue(
        100000
    )
    assert bound_log == []

    # Reverse operand order stays constructed.
    reversed_outcome, reversed_log = _reduce_outcome_with_log("100000 * [0]")
    reversed_value = complete_value(
        reversed_outcome, owner="test_loc reverse ground sequence_repeat"
    )
    assert isinstance(reversed_value, GroundSequenceRepetitionValue)
    assert reversed_value.repetitions == 100000
    assert reversed_log == []


def test_tuple_repetition_by_symbolic_count_is_typed_runtime_effect():
    outcome, operation_log = _reduce_outcome_with_log(
        "(1,) * count",
        {"count": SymbolicValue(make_var("count"))},
    )

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "SequenceRepetitionRuntimeEffect"
    assert "sequence repetition by symbolic count" in outcome.reason
    assert outcome.effect.witness is not None
    assert outcome.effect.witness.operand == make_var("count")
    assert outcome.effect.witness.operation == ctor(
        "py.sequence_repeat", [make_var("count")]
    )
    assert operation_log == []


def test_large_ground_tuple_repetition_is_compact_construction():
    outcome, operation_log = _reduce_outcome_with_log("(1,) * 65521")

    value = complete_value(outcome, owner="large ground tuple repetition")
    assert fol(value.to_term(owner="test")) == fol(
        ctor("*", [ctor("tuple", [num(1)]), num(65521)])
    )
    assert complete_value(value.length("t.py:1:0"), owner="repetition length") == (
        TermValue(65521)
    )
    assert operation_log == []


def test_large_ground_array_literal_repetition_is_compact_construction():
    value = ArrayLiteral((TermValue(1),))

    outcome = value.multiply(TermValue(65521), "t.py:1:0")

    repeated = complete_value(outcome, owner="large ground array repetition")
    assert fol(repeated.to_term(owner="test")) == fol(
        ctor("*", [ctor("array", [num(1)]), num(65521)])
    )
    assert complete_value(
        repeated.length("t.py:1:0"), owner="repetition length"
    ) == TermValue(65521)


def test_list_repetition_by_symbolic_count_is_typed_runtime_effect():
    outcome, operation_log = _reduce_outcome_with_log(
        "items * count",
        {
            "items": ArrayLiteral((SymbolicValue(make_var("x")),)),
            "count": SymbolicValue(make_var("count")),
        },
    )

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "SequenceRepetitionRuntimeEffect"
    assert "sequence repetition by symbolic count" in outcome.reason
    assert operation_log == []
