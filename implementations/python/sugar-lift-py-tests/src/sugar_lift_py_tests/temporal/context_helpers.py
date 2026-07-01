from __future__ import annotations

from dataclasses import replace
from typing import Any

from sugar_lift_py_tests.floor import FloorValue

from .bind_value_operation import BindValueOperation
from .curry_arguments_operation import CurryArgumentsOperation
from .perform_temporal_operation import perform_temporal_operation
from .temporal_context import TemporalContext


def bind_temporal(
    ctx: Any,
    name: str,
    value: FloorValue,
    *,
    owner: str,
    blame: str,
) -> Any:
    return _ctx_with_temporal(
        ctx,
        perform_temporal_operation(
            owner=owner,
            blame=blame,
            receiver=getattr(ctx, "temporal", TemporalContext.empty()),
            method_name="bind_with",
            operation=BindValueOperation(
                name=name,
                value=value,
                owner=owner,
                blame=blame,
            ),
            ctx=ctx,
        ),
    )


def curry_temporal(
    ctx: Any,
    parameters: tuple[str, ...],
    arg_values: tuple[FloorValue, ...],
    *,
    owner: str,
    blame: str,
) -> Any:
    return _ctx_with_temporal(
        ctx,
        perform_temporal_operation(
            owner=owner,
            blame=blame,
            receiver=getattr(ctx, "temporal", TemporalContext.empty()),
            method_name="curry_with",
            operation=CurryArgumentsOperation(
                parameters=parameters,
                arg_values=arg_values,
                owner=owner,
                blame=blame,
            ),
            ctx=ctx,
        ),
    )


def rewrite_temporal(ctx: Any, operation: object, *, owner: str, blame: str) -> Any:
    return _ctx_with_temporal(
        ctx,
        perform_temporal_operation(
            owner=owner,
            blame=blame,
            receiver=getattr(ctx, "temporal", TemporalContext.empty()),
            method_name="rewrite_with",
            operation=operation,
            ctx=ctx,
        ),
    )


def _ctx_with_temporal(ctx: Any, temporal: TemporalContext) -> Any:
    if hasattr(ctx, "with_temporal"):
        return ctx.with_temporal(temporal)
    if ctx is None:
        from sugar_lift_py_tests.context.reduce_context import ReduceContext

        return ReduceContext(temporal=temporal)
    return replace(ctx, temporal=temporal)
