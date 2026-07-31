from __future__ import annotations

from dataclasses import dataclass, field
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
    can_fall_through: bool = True
    # Final temporal state of this exact completed block face.  It is runtime
    # projection testimony, not part of BlockValue's semantic equality/term.
    final_context: object | None = field(default=None, compare=False, repr=False)

    def guarded(self, formula):
        """Guard every suite entry through that entry's own Floor law."""
        from dataclasses import replace

        return replace(
            self,
            statements=tuple(entry.guarded(formula) for entry in self.statements),
        )

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
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.outcome.follow_step import FollowStep

        if any(type(entry) is ReturnValue for entry in self.statements):
            return FollowStep.halt(keeps_rest=True)
        if any(type(entry) is RaiseValue for entry in self.statements):
            return FollowStep.halt(keeps_rest=False)
        if any(
            isinstance(entry, Incomplete)
            and not entry.branch_conditions
            and not entry.follow().continues
            for entry in self.statements
        ):
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
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.outcome import Incomplete

        op_label = getattr(operation, "operator", kind)
        if len(self.statements) != 1 or self.fall_through:
            return Incomplete(
                BlockOperatorRuntimeEffect(
                    f"block {kind} operator runtime boundary: multi-exit or "
                    f"fall-through block cannot host `{op_label}` "
                    f"statically; keep as typed red until branch-wise {kind} "
                    f"floors own this shape. blame={operation.blame}",
                    **runtime_effect_evidence(f"py.block_{kind}", op_label, operation),
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
                    **runtime_effect_evidence(f"py.block_{kind}", op_label, operation),
                )
            )
        # The central `perform_operation` dispatcher died with the operations
        # layer (b0aadef50). The rebuilt layer has no centre: an operation
        # submits ITSELF to a value (`operations/sequence_projection_operation.py
        # ::submit` — "ask the value what it unpacks to; the value owns the
        # answer"), which is the same `getattr(receiver, method_name)(op, ctx)`
        # the dispatcher performed. A value with no arm still panics loudly:
        # `FloorValue` owns a construction-gap base for every operation method.
        return operation.submit(exit_value, ctx)
