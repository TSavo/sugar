from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.sugar_body import SugarBody

from .floor_value import FloorValue


@dataclass(frozen=True)
class CallSiteValue(FloorValue):
    """A callsite as two things at once.

    The `term` is the bridge/culture coordinate used by contract composition.
    The factory-built `body` is only reduced when a downstream floor demands a
    concrete value (for example, a list literal index).
    """

    target_name: str
    arg_values: tuple[FloorValue, ...]
    parameters: tuple[str, ...]
    term: Term
    body: SugarBody | None

    def to_term(self, *, owner: str):
        del owner
        return self.term

    def project_callsite_with(self, operation, ctx):
        return operation.project_callsite(self, ctx)

    def force_floor(self, ctx: Any, *, owner: str, seen: frozenset[str] = frozenset()):
        key = repr(self.term)
        if key in seen:
            raise TypeError(
                f"write more Floor for {owner}: recursive callsite value demand "
                f"for `{self.target_name}`"
            )
        if self.body is None:
            raise TypeError(
                f"write more Floor for {owner}: callsite `{self.target_name}` has "
                "no resolved body to demand"
            )
        if len(self.parameters) != len(self.arg_values):
            raise TypeError(
                f"write more Floor for {owner}: callsite `{self.target_name}` "
                "argument count does not match its body"
            )
        from sugar_lift_py_tests.outcome import Incomplete, complete_value

        reduce_ctx = _ctx_with_curried_args(ctx, self.parameters, self.arg_values)
        outcome = self.body.reduce(reduce_ctx)
        if isinstance(outcome, Incomplete):
            raise TypeError(
                f"write more Floor for {owner}: callsite `{self.target_name}` "
                "reduced to a runtime effect"
            )
        value = complete_value(outcome, owner=owner)
        return force_floor(value, reduce_ctx, owner=owner, seen=seen | {key})


def force_floor(
    value: FloorValue,
    ctx: Any,
    *,
    owner: str,
    seen: frozenset[str] = frozenset(),
) -> FloorValue:
    if isinstance(value, CallSiteValue):
        return value.force_floor(ctx, owner=owner, seen=seen)
    return value


def _ctx_with_curried_args(
    ctx: Any,
    parameters: tuple[str, ...],
    arg_values: tuple[FloorValue, ...],
):
    from sugar_lift_py_tests.temporal import curry_temporal

    return curry_temporal(
        ctx,
        parameters,
        arg_values,
        owner="CallSiteValue.force_floor",
        blame="<callsite>",
    )
