"""Explicit handler-owned in-flight effect context; never ambient state."""

from __future__ import annotations


def bind_in_flight_effect(ctx, slot_id: str, effect, *, blame: object):
    if ctx is None:
        from sugar_lift_py_tests.context.reduce_context import ReduceContext

        ctx = ReduceContext.root(owner="bind_in_flight_effect")
    binder = getattr(ctx, "with_in_flight_effect", None)
    if binder is None:
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=blame,
            owner="bind_in_flight_effect",
            observed="reduction context cannot carry authenticated in-flight effects",
            requested="the shared ReduceContext/FactoryBuildContext effect slot",
            fix="route handler reduction through the one effect context",
        )
    return binder(slot_id, effect)


def resolve_in_flight_effect(ctx, slot_id: str, *, blame: object):
    reader = getattr(ctx, "in_flight_effect_for", None) if ctx is not None else None
    effect = reader(slot_id) if reader is not None else None
    if effect is None:
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=blame,
            owner="resolve_in_flight_effect",
            observed="bare raise has no authenticated in-flight effect testimony",
            requested="the exact RaiseEffect bound by its matching handler slot",
            fix="keep unowned or stale-slot bare raise loud",
        )
    return effect
