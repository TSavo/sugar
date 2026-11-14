from __future__ import annotations

from dataclasses import replace
from typing import Any

from sugar_lift_py_tests.floor import FloorValue

from .temporal_context import TemporalContext


def bind_temporal(
    ctx: Any,
    name: str,
    value: FloorValue,
    *,
    owner: str,
    blame: str,
) -> Any:
    del owner
    return _ctx_with_temporal(
        ctx, _ctx_temporal(ctx).bind_value(name, value, blame=blame)
    )


def curry_temporal(
    ctx: Any,
    parameters: tuple[str, ...],
    arg_values: tuple[FloorValue, ...],
    *,
    owner: str,
    blame: str,
) -> Any:
    if len(parameters) != len(arg_values):
        raise TypeError(
            f"write more Floor for {owner}: temporal curry argument count "
            "does not match parameters"
        )
    temporal = _ctx_temporal(ctx)
    for name, value in zip(parameters, arg_values, strict=True):
        temporal = temporal.bind_value(name, value, blame=blame)
    return _ctx_with_temporal(ctx, temporal)


def _ctx_temporal(ctx: Any) -> TemporalContext:
    if ctx is None:
        return TemporalContext.empty()
    return ctx.temporal


def _ctx_with_temporal(ctx: Any, temporal: TemporalContext) -> Any:
    if ctx is None:
        from sugar_lift_py_tests.context.reduce_context import ReduceContext

        return ReduceContext(temporal=temporal)
    return replace(ctx, temporal=temporal)
