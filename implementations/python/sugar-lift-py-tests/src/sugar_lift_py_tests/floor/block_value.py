from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class BlockValue(FloorValue):
    """The composed outcome of a block (a suite): the ordered return outcomes of its
    statements (Support absorbed, lets threaded). `fall_through` is the guard under
    which execution leaves the block without returning -- it is `()` for an
    exhaustive block (every path returns) and `(not test,)` for a trailing
    `if test: return ...` with no else, so the ENCLOSING block guards later
    statements by it."""

    statements: tuple[object, ...]
    fall_through: tuple = ()

    def contribution(self):
        # A block inside a record splices: its entries ARE the entries.
        return self.statements

    def inv_contribution(self):
        return tuple(
            formula for entry in self.statements for formula in entry.inv_contribution()
        )

    def post_contribution(self):
        return tuple(
            formula
            for entry in self.statements
            for formula in entry.post_contribution()
        )

    def follow_rest(self):
        # Only an *unguarded* return or raise makes the entire continuation
        # unreachable. GuardedReturn / GuardedRaise (if/except path) coexist
        # with a live tail — e.g. try/except: return|raise; assert ... must
        # still reduce the assert on the non-exception path.
        from sugar_lift_py_tests.floor.raise_value import RaiseValue
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.outcome.follow_step import FollowStep

        if any(type(entry) is ReturnValue for entry in self.statements):
            return FollowStep.halt(keeps_rest=True)
        if any(type(entry) is RaiseValue for entry in self.statements):
            return FollowStep.halt(keeps_rest=False)
        return FollowStep.continue_with()

    def extend_scope(self, ctx):
        # Nested with / pytest.raises as-bindings live on entries (RaisesWithValue,
        # ScopeRebind). Thread them into the *rest of the enclosing block* so
        # ``with freeze_time: with raises as exc_info: ...; assert exc_info`` works.
        for entry in self.statements:
            if hasattr(entry, "extend_scope"):
                ctx = entry.extend_scope(ctx)
        return ctx

    def guard_with(self, operation: Any, ctx: Any) -> Any:
        return operation.guard_block(self, ctx)

    def route_raises_with(self, operation: Any, ctx: Any) -> Any:
        return operation.route_block_raises(self, ctx)

    def merge_finally_with(self, operation: Any, ctx: Any) -> Any:
        return operation.merge_finally_block(self, ctx)

    def project_callsite_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_block(self, ctx)

    def binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        """Binary op on a dug function-body block (revealed after CallSiteValue).

        Single-exit blocks re-dispatch on the exit floor (unwrap ReturnValue);
        multi-exit / fall-through stays typed RuntimeEffect. Never invent a
        merged numeric result across branches.
        """
        return self._redispatch_operator(operation, ctx, kind="binary")

    def unary_operator_with(self, operation: Any, ctx: Any) -> Any:
        """Unary op on a dug function-body block (revealed with binary path).

        Same single-exit redispatch as binary_operator_with.
        """
        return self._redispatch_operator(operation, ctx, kind="unary")

    def subscript_with(self, operation: Any, ctx: Any) -> Any:
        """Subscript on a dug function-body block (revealed after binary dig)."""
        return self._redispatch_operator(operation, ctx, kind="subscript")

    def _redispatch_operator(self, operation: Any, ctx: Any, *, kind: str) -> Any:
        from sugar_lift_py_tests.effect import (
            BlockOperatorRuntimeEffect,
            runtime_effect_witness,
        )
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.operations.perform_operation import perform_operation
        from sugar_lift_py_tests.outcome import Incomplete

        op_label = getattr(operation, "operator", kind)
        if len(self.statements) != 1 or self.fall_through:
            return Incomplete(
                BlockOperatorRuntimeEffect(
                    f"block {kind} operator runtime boundary: multi-exit or "
                    f"fall-through block cannot host `{op_label}` "
                    f"statically; keep as typed red until branch-wise {kind} "
                    f"floors own this shape. blame={operation.blame}",
                    witness=runtime_effect_witness(
                        f"py.block_{kind}", op_label, operation
                    ),
                )
            )
        exit_value = self.statements[0]
        if isinstance(exit_value, ReturnValue):
            exit_value = exit_value.value
        if not isinstance(exit_value, FloorValue):
            return Incomplete(
                BlockOperatorRuntimeEffect(
                    f"block {kind} operator runtime boundary: single exit is "
                    f"`{type(exit_value).__name__}`, not a FloorValue; "
                    f"blame={operation.blame}",
                    witness=runtime_effect_witness(
                        f"py.block_{kind}", op_label, operation
                    ),
                )
            )
        return perform_operation(
            owner=operation.owner,
            blame=operation.blame,
            receiver=exit_value,
            operation=operation,
            ctx=ctx,
        )
