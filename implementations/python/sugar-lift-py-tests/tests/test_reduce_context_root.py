from __future__ import annotations

from sugar_lift_py_tests.context.reduce_context import ReduceContext


def test_root_mints_empty_temporal() -> None:
    ctx = ReduceContext.root(owner="test")

    assert ctx.temporal.bindings == ()


def test_derived_carries_temporal_forward() -> None:
    base = ReduceContext.root(owner="test")
    from sugar_lift_py_tests.temporal import bind_temporal

    bound = bind_temporal(base, "x", object(), owner="test", blame="t:1")
    derived = ReduceContext.derived(bound, owner="test")

    assert derived.temporal is bound.temporal


def test_derived_carries_dig_sink_forward() -> None:
    sink: list[tuple[str, object]] = []
    base = ReduceContext.root(owner="test", dig_sink=sink)

    derived = ReduceContext.derived(base, owner="test")

    assert derived.dig_sink is sink


def test_root_exposes_external_bridge_sink() -> None:
    """CallSugar.ExternalBridgeStrategy reads ctx.external_bridge_sink on reduce.

    Missing the attribute crashed the numpy/pandas package audit as unstructured
    exit=2 once body dig reduced vendor-bridged callees through ReduceContext.
    """
    ctx = ReduceContext.root(owner="test")
    assert hasattr(ctx, "external_bridge_sink")
    assert ctx.external_bridge_sink is None


def test_derived_carries_external_bridge_sink_forward() -> None:
    sink: list[dict] = []
    base = ReduceContext.root(owner="test", external_bridge_sink=sink)

    derived = ReduceContext.derived(base, owner="test")

    assert derived.external_bridge_sink is sink
    assert derived.with_temporal(derived.temporal).external_bridge_sink is sink
