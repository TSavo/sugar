"""Truth is a floor: concrete values fold their own Python truth to the True/False
literal; symbolic values emit the operator-indexed atom py.truthy(x). The lattice
wires binary_conditional and stated through truth -- no new forks at the sugar."""

from __future__ import annotations

import ast
from dataclasses import replace

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import AssertionFailedRuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    BlockValue,
    FloorValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
    UniverseValue,
)
from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
from sugar_lift_py_tests.ir import and_, eq, implies, make_var, not_, num, py_truthy
from sugar_lift_py_tests.outcome import Incomplete, complete_value


def _universe(source: str) -> UniverseValue:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert isinstance(value, UniverseValue)
    return value


def test_concrete_nonzero_int_picks_the_then_face() -> None:
    # `if 5:` folds True -- then runs, the else return stays raw.
    block = compose_block("    if 5:\n        return 1\n    return 2\n")
    assert isinstance(block, BlockValue)
    assert block.statements[0] == ReturnValue(TermValue(1))
    assert len(block.statements) == 2  # trailing return is raw, unreduced


def test_empty_string_is_false() -> None:
    block = compose_block('    if "":\n        return 1\n    return 2\n')
    assert block == BlockValue((ReturnValue(TermValue(2)),))


def test_none_is_false() -> None:
    block = compose_block("    if None:\n        return 1\n    return 2\n")
    assert block == BlockValue((ReturnValue(TermValue(2)),))


def test_assert_nonzero_folds_true_to_support() -> None:
    assert compose_block("    assert 5\n    return 2\n") == BlockValue(
        (ReturnValue(TermValue(2)),)
    )


def test_assert_zero_is_the_named_halt() -> None:
    record = compose_block("    assert 0\n    return 2\n").statements
    assert isinstance(record[0], Incomplete)
    assert isinstance(record[0].effect, AssertionFailedRuntimeEffect)
    assert len(record) == 2


def test_symbolic_condition_emits_py_truthy_guard() -> None:
    from sugar_lift_py_tests.ir import py_truthy

    universe = _universe(
        "def A(z):\n    if z:\n        return 1\n    return 0\n"
    )
    guard = py_truthy(make_var("z"))
    assert universe.post() == and_(
        [
            implies(guard, eq(make_var("out"), num(1))),
            implies(not_(guard), eq(make_var("out"), num(0))),
        ]
    )


def test_symbolic_condition_propagates_named_runtime_effect() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    ctx = replace(
        ctx,
        temporal=ctx.temporal.bind_value(
            "z", SymbolicValue(make_var("z"))
        ),
    )
    node = ast.parse("if z:\n    assert 0\n").body[0]
    result = build_node(
        node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx
    )

    outcome = result.sugar.desugar(ctx)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, AssertionFailedRuntimeEffect)
    assert "under branch condition" in outcome.reason
    assert "py.truthy" in outcome.reason


def test_floor_value_default_truth_panics() -> None:
    # No honest source-level case for a value with no Python truth is in scope
    # yet; the default construction-gap is the contract.
    with pytest.raises(FactoryPanic, match="stand as a condition"):
        FloorValue().truth(site=None)


def test_opaque_operator_callsite_truth_cites_its_existing_coordinate() -> None:
    callsite = OpaqueOpCallsite("len", SymbolicValue(make_var("items")))

    outcome = callsite.truth(site="t.py:1:3")
    predicate = complete_value(outcome, owner="test")

    assert predicate.formula == py_truthy(callsite.to_term(owner="test"))
