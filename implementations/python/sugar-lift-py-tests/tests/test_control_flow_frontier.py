from __future__ import annotations

from dataclasses import replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import (
    BlockValue,
    GuardedRaise,
    GuardedReturn,
    RaiseValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import gt, make_var, not_, num
from sugar_lift_py_tests.operations import (
    ControlFlowGuardOperation,
    FinallyFallthroughOperation,
    RouteRaisesOperation,
    perform_operation,
)
from sugar_lift_py_tests.outcome import Complete, complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def test_block_frontier_guards_return_and_raise_paths_by_dispatch() -> None:
    guard = gt(make_var("x"), num(0))
    block = BlockValue(
        (
            ReturnValue(TermValue(1)),
            RaiseValue(RaiseEffect("ValueError", "raise ValueError")),
        )
    )
    ctx = ReduceContext(temporal=TemporalContext.empty())

    outcome = perform_operation(
        owner="IfSugar",
        blame="f.py:2:4",
        receiver=block,
        method_name="guard_with",
        operation=ControlFlowGuardOperation(
            (guard,), owner="IfSugar", blame="f.py:2:4"
        ),
        ctx=ctx,
    )

    assert complete_value(outcome, owner="guarded block") == BlockValue(
        (
            GuardedReturn((guard,), TermValue(1)),
            GuardedRaise((guard,), RaiseEffect("ValueError", "raise ValueError")),
        )
    )
    assert ctx.operation_log == [("IfSugar", "guard_with", "ControlFlowGuardOperation")]


def test_block_frontier_routes_guarded_raise_through_matching_handler_scope() -> None:
    guard = gt(make_var("x"), num(0))
    captured_scope = ReduceContext(
        temporal=TemporalContext.empty().bind_value(
            "y", SymbolicValue(make_var("captured_y"))
        )
    )
    effect = RaiseEffect("ValueError", "raise ValueError")
    block = BlockValue((GuardedRaise((guard,), effect, scope=captured_scope),))
    outer_ctx = ReduceContext(temporal=TemporalContext.empty())
    handler = _ReturningHandler(expected_ctx=captured_scope, value=TermValue(5))

    outcome = perform_operation(
        owner="TrySugar",
        blame="f.py:2:4",
        receiver=block,
        method_name="route_raises_with",
        operation=RouteRaisesOperation((handler,), owner="TrySugar", blame="f.py:2:4"),
        ctx=outer_ctx,
    )

    assert complete_value(outcome, owner="routed block") == BlockValue(
        (GuardedReturn((guard,), TermValue(5)),)
    )
    assert outer_ctx.operation_log == [
        ("TrySugar", "route_raises_with", "RouteRaisesOperation"),
        ("TrySugar", "guard_with", "ControlFlowGuardOperation"),
    ]


def test_block_frontier_merges_finally_fallthrough_by_dispatch() -> None:
    cleanup_guard = gt(make_var("x"), num(0))
    fallthrough_guard = not_(cleanup_guard)
    final_block = BlockValue(
        (GuardedReturn((cleanup_guard,), TermValue(2)),),
        fall_through=(fallthrough_guard,),
    )
    incoming_block = BlockValue((ReturnValue(TermValue(1)),))
    ctx = ReduceContext(temporal=TemporalContext.empty())

    outcome = perform_operation(
        owner="TrySugar.finally",
        blame="f.py:4:4",
        receiver=final_block,
        method_name="merge_finally_with",
        operation=FinallyFallthroughOperation(
            incoming_block=incoming_block,
            owner="TrySugar.finally",
            blame="f.py:4:4",
        ),
        ctx=ctx,
    )

    assert complete_value(outcome, owner="finally merge") == BlockValue(
        (
            GuardedReturn((cleanup_guard,), TermValue(2)),
            GuardedReturn((fallthrough_guard,), TermValue(1)),
        )
    )
    assert ctx.operation_log == [
        ("TrySugar.finally", "merge_finally_with", "FinallyFallthroughOperation"),
        ("TrySugar.finally", "guard_with", "ControlFlowGuardOperation"),
    ]


def test_if_sugar_guards_branch_frontiers_by_floor_dispatch() -> None:
    value, operation_log = _reduce_block_with_log(
        '    if x > 0:\n        return "a"\n    else:\n        return "b"\n',
        {"x": SymbolicValue(make_var("x"))},
    )

    assert isinstance(value, BlockValue)
    assert operation_log == [
        ("IfSugar", "guard_with", "ControlFlowGuardOperation"),
        ("IfSugar", "guard_with", "ControlFlowGuardOperation"),
    ]


def test_try_sugar_routes_raise_frontiers_by_floor_dispatch() -> None:
    value, operation_log = _reduce_block_with_log(
        "    try:\n"
        "        if x > 0:\n"
        "            raise ValueError('boom')\n"
        "        return x + 1\n"
        "    except ValueError:\n"
        "        return x + 2\n",
        {"x": SymbolicValue(make_var("x"))},
    )

    assert isinstance(value, BlockValue)
    assert operation_log == [
        ("IfSugar", "guard_with", "ControlFlowGuardOperation"),
        ("BinOpSugar", "binary_operator_with", "BinaryOperatorOperation"),
        ("BlockSugar", "guard_with", "ControlFlowGuardOperation"),
        ("TrySugar", "route_raises_with", "RouteRaisesOperation"),
        ("BinOpSugar", "binary_operator_with", "BinaryOperatorOperation"),
        ("TrySugar", "guard_with", "ControlFlowGuardOperation"),
    ]


def test_block_sugar_guards_fallthrough_exits_by_floor_dispatch() -> None:
    value, operation_log = _reduce_block_with_log(
        "    if x > 0:\n" "        return x + 1\n" "    return x + 2\n",
        {"x": SymbolicValue(make_var("x"))},
    )

    assert isinstance(value, BlockValue)
    assert operation_log == [
        ("BinOpSugar", "binary_operator_with", "BinaryOperatorOperation"),
        ("IfSugar", "guard_with", "ControlFlowGuardOperation"),
        ("BinOpSugar", "binary_operator_with", "BinaryOperatorOperation"),
        ("BlockSugar", "guard_with", "ControlFlowGuardOperation"),
    ]


class _ReturningHandler:
    def __init__(self, *, expected_ctx, value: TermValue) -> None:
        self.expected_ctx = expected_ctx
        self.value = value

    def matches(self, effect: RaiseEffect) -> bool:
        return effect.exception_name == "ValueError"

    def reduce(self, ctx, effect: RaiseEffect):
        assert ctx is self.expected_ctx
        assert effect.exception_name == "ValueError"
        return Complete(BlockValue((ReturnValue(self.value),)))


def _reduce_block_with_log(body_src: str, binds: dict):
    import ast

    fn = ast.parse(f"def f(x):\n{body_src}").body[0]
    block = Block.of(fn.body)
    temporal = TemporalContext.empty()
    for name, value in binds.items():
        temporal = temporal.bind_value(name, value)
    build_ctx = FactoryBuildContext(
        filename="f.py",
        catalog=default_catalog(),
        temporal=temporal,
    )
    result = build_node(block, filename="f.py", role=SugarRole.STATEMENT, ctx=build_ctx)
    reduce_ctx = ReduceContext(temporal=temporal)
    outcome = result.sugar.desugar(replace(reduce_ctx, temporal=temporal))
    return (
        complete_value(outcome, owner="control-flow frontier test"),
        reduce_ctx.operation_log,
    )
