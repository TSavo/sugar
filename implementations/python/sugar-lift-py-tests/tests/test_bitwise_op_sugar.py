"""BitwiseOpSugar reduces Python bit operators to the canonical bv32 ctors."""

from __future__ import annotations

import ast

import pytest

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import factory_panic
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    Bv32Value,
    ComprehensionValue,
    PredicateValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import and_, atomic, ctor, make_var, not_, num, or_
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.outcome import Complete, complete_value
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.runtime_bitwise_op_sugar import RuntimeBitwiseOpSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _x():
    return {"x": Bv32Value(make_var("x"))}


def test_bitwise_and_reduces_to_bv32_and():
    assert fol(reduce_term("x & 15", _x())) == fol(
        ctor("bv32.and", [make_var("x"), num(15)])
    )


def test_predicate_bitwise_and_constructs_formula_conjunction() -> None:
    site = SourceFragment.from_source("left & right\n", "t.py").statements()[0]
    left = PredicateValue(atomic("left", []), site)
    right = PredicateValue(atomic("right", []), site)

    outcome = left.bitwise_and(right, site)

    assert outcome == Complete(
        PredicateValue(and_([left.formula, right.formula]), site)
    )


def test_predicate_bitwise_and_nonpredicate_wrong_twin_stays_loud() -> None:
    site = SourceFragment.from_source("left & right\n", "t.py").statements()[0]
    left = PredicateValue(atomic("left", []), site)

    with pytest.raises(FactoryPanic, match=r"owner=bitwise_and.*PredicateValue"):
        left.bitwise_and(StringValue("right"), site)


def test_predicate_bitwise_and_symbolic_rhs_keeps_exact_coordinate() -> None:
    site = SourceFragment.from_source("left & right\n", "t.py").statements()[0]
    left = PredicateValue(atomic("left", []), site)
    right = SymbolicValue(make_var("right"))

    outcome = left.bitwise_and(right, site)

    assert outcome == Complete(
        SymbolicValue(ctor("&", [left.to_term(owner="test"), right.term]))
    )


def test_predicate_bitwise_and_conserves_assertion_without_an_effect() -> None:
    source = "def test_a(x):\n    assert (x == 1) & (x == 2)\n"

    payload, gaps = audit_lift_file(source, "predicate_and.py")
    rpc = payload.to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file="predicate_and.py"), rpc
    ).to_json()["assertions"]

    assert gaps == []
    assert rpc["effects"] == []
    assert assertions["stated"] == 1
    assert assertions["lifted_cited"] == 1
    assert assertions["silently_unaccounted"] == 0


def test_predicate_bitwise_and_truthful_and_lying_twins_refute(tmp_path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        "def test_a(x):\n    assert (x == 1) & (x == 1)\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        "def test_a(x):\n    assert (x == 1) & (not (x == 1))\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "RuntimeBitwiseOpSugar" in truthful.selected_sugars
    assert "RuntimeBitwiseOpSugar" in lying.selected_sugars


def test_predicate_bitwise_xor_constructs_exclusive_disjunction() -> None:
    site = SourceFragment.from_source("left ^ right\n", "t.py").statements()[0]
    left = PredicateValue(atomic("left", []), site)
    right = PredicateValue(atomic("right", []), site)

    outcome = left.bitwise_xor(right, site)

    assert outcome == Complete(
        PredicateValue(
            or_(
                [
                    and_([left.formula, not_(right.formula)]),
                    and_([not_(left.formula), right.formula]),
                ]
            ),
            site,
        )
    )


def test_predicate_bitwise_xor_nonpredicate_wrong_twin_stays_loud() -> None:
    site = SourceFragment.from_source("left ^ right\n", "t.py").statements()[0]
    left = PredicateValue(atomic("left", []), site)

    with pytest.raises(FactoryPanic, match=r"owner=bitwise_xor.*PredicateValue"):
        left.bitwise_xor(StringValue("right"), site)


def test_predicate_bitwise_xor_conserves_assertion_without_an_effect() -> None:
    source = "def test_a(x):\n    assert (x == 1) ^ (x == 2)\n"

    payload, gaps = audit_lift_file(source, "predicate_xor.py")
    rpc = payload.to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file="predicate_xor.py"), rpc
    ).to_json()["assertions"]

    assert gaps == []
    assert rpc["effects"] == []
    assert assertions["stated"] == 1
    assert assertions["lifted_cited"] == 1
    assert assertions["silently_unaccounted"] == 0


def test_predicate_bitwise_xor_truthful_and_lying_twins_refute(tmp_path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        "def test_a(x):\n    assert x == 1\n    assert (x == 1) ^ (x == 2)\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        "def test_a(x):\n    assert x == 1\n    assert (x == 1) ^ (x == 1)\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "RuntimeBitwiseOpSugar" in truthful.selected_sugars
    assert "RuntimeBitwiseOpSugar" in lying.selected_sugars


@pytest.mark.parametrize(
    ("left_type", "right_type", "result_type"),
    [
        (FalseBoolLiteralSugar, FalseBoolLiteralSugar, FalseBoolLiteralSugar),
        (FalseBoolLiteralSugar, TrueBoolLiteralSugar, TrueBoolLiteralSugar),
        (TrueBoolLiteralSugar, FalseBoolLiteralSugar, TrueBoolLiteralSugar),
        (TrueBoolLiteralSugar, TrueBoolLiteralSugar, FalseBoolLiteralSugar),
    ],
)
def test_bool_literal_bitwise_xor_constructs_exact_truth_table(
    left_type, right_type, result_type
) -> None:
    site = SourceFragment.from_source("left ^ right\n", "t.py").statements()[0]

    outcome = left_type(site).bitwise_xor(right_type(site), site)

    assert outcome == Complete(result_type(site))


def test_bool_literal_bitwise_xor_nonbool_wrong_twin_stays_loud() -> None:
    site = SourceFragment.from_source("left ^ right\n", "t.py").statements()[0]

    with pytest.raises(FactoryPanic, match=r"owner=bitwise_xor.*TrueBoolLiteralSugar"):
        TrueBoolLiteralSugar(site).bitwise_xor(StringValue("right"), site)


def test_bool_literal_bitwise_xor_truthful_and_lying_twins_refute(tmp_path) -> None:
    prefix = "def A():\n    return True ^ False\n\n"
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        prefix + "def test_a():\n    assert A() == True\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        prefix + "def test_a():\n    assert A() == False\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "RuntimeBitwiseOpSugar" in truthful.selected_sugars
    assert "RuntimeBitwiseOpSugar" in lying.selected_sugars


def test_bitwise_rshift_reduces_to_bv32_lshr():
    assert fol(reduce_term("x >> 2", _x())) == fol(
        ctor("bv32.lshr", [make_var("x"), num(2)])
    )


def test_bitwise_or_dispatches_bv32_receiver_to_floor_operation():
    result, operation_log = _reduce_value_with_log("x | 3", _x())

    assert result == Bv32Value(ctor("bv32.or", [make_var("x"), num(3)]))
    assert operation_log == [("BitwiseOpSugar", "bitwise_with", "BitwiseOperation")]


def test_set_comprehension_union_constructs_exact_coordinate() -> None:
    site = SourceFragment.from_source("left | right\n", "t.py").statements()[0]
    left = ComprehensionValue(
        ctor(
            "py.set_difference",
            [
                ctor("py.setcomp", [make_var("all_items")]),
                ctor("py.setcomp", [make_var("excluded_items")]),
            ],
        )
    )
    right = ComprehensionValue(ctor("py.setcomp", [make_var("new_items")]))

    outcome = left.bitwise_or(right, site)

    assert outcome == Complete(
        ComprehensionValue(ctor("py.set_union", [left.term, right.term]))
    )


def test_list_comprehension_bitwise_or_stays_loud() -> None:
    site = SourceFragment.from_source("left | right\n", "t.py").statements()[0]
    left = ComprehensionValue(ctor("py.listcomp", [make_var("left_items")]))
    right = ComprehensionValue(ctor("py.listcomp", [make_var("right_items")]))

    with pytest.raises(FactoryPanic, match="owner=bitwise_or"):
        left.bitwise_or(right, site)


def test_set_comprehension_union_truthful_and_lying_twins_refute(tmp_path) -> None:
    pair = next(
        pair
        for pair in RuntimeBitwiseOpSugar.witnesses()
        if pair.name == "set_comprehension_union"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful-set-union", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying-set-union", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"
    assert "RuntimeBitwiseOpSugar" in truthful.selected_sugars
    assert "RuntimeBitwiseOpSugar" in lying.selected_sugars


def test_bitwise_lshift_dispatches_term_receiver_without_python_solving():
    result, operation_log = _reduce_value_with_log("1 << x", _x())

    assert result == Bv32Value(ctor("bv32.shl", [num(1), make_var("x")]))
    assert operation_log == [("BitwiseOpSugar", "bitwise_with", "BitwiseOperation")]


def test_concrete_bitwise_literals_fold_to_int_term():
    result, operation_log = _reduce_value_with_log("3 & 1")

    assert result == TermValue(1)
    assert operation_log == [("BitwiseOpSugar", "bitwise_with", "BitwiseOperation")]


def test_concrete_bitwise_shift_literals_fold_to_int_term():
    result, operation_log = _reduce_value_with_log("1 << 2")

    assert result == TermValue(4)
    assert operation_log == [("BitwiseOpSugar", "bitwise_with", "BitwiseOperation")]


def test_bitwise_xor_dispatches_bv32_receiver_to_floor_operation():
    result, operation_log = _reduce_value_with_log("x ^ 3", _x())

    assert result == Bv32Value(ctor("bv32.xor", [make_var("x"), num(3)]))
    assert operation_log == [("BitwiseOpSugar", "bitwise_with", "BitwiseOperation")]


def test_bitwise_missing_receiver_capability_is_a_named_floor_gap():
    with pytest.raises(FactoryGap) as raised:
        _reduce_value_with_log("'bad' & 1")

    assert raised.value.info.to_json() == {
        "owner": "BitwiseOpSugar",
        "blame": "t.py:1:0",
        "observed": "StringValue",
        "requested": "bitwise_with",
        "fix": "add bitwise_with to StringValue or emit a real effect",
        "gap_kind": "Floor",
        "gap_locus": "Construction",
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
