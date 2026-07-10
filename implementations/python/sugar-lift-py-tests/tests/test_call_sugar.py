"""CallSugar -- the dumb call shell + its strategies (CALLSUGAR_REFACTOR_GOAL.md).

Step 2 scope: the dumb shell (owns=shape, build=router, desugar=delegate) and the
real FactoryGapStrategy. BridgeStrategy / AssertionFactStrategy (the in-body EUF
bridge + dig, and the sworn fact) land in Steps 3-4 with their own tests. No
NotImplementedError stubs here.
"""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
from sugar_lift_py_tests.factory.build import FactoryBuildContext, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.call_sugar import (
    CallSugar,
    ExternalBridgeStrategy,
    FactoryGapStrategy,
)


def _frag(expr: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body, "t.py")


def _build(expr: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    return ctx.build_body(_frag(expr), SugarRole.TERM), ctx


def _reduce_gap_effect(body, ctx) -> FactoryGapEffect:
    outcome = body.reduce(ctx)
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect)
    return outcome.effect


# --- owns is SHAPE ONLY -----------------------------------------------------------------


def test_owns_is_shape_only_a_call_yes_a_non_call_no():
    assert CallSugar.owns(_frag("f(1)")) is True
    assert CallSugar.owns(_frag("5")) is False
    assert CallSugar.owns(_frag("x + 1")) is False


def test_build_is_a_single_delegation_no_context_branch():
    # structural: the post-template hook only delegates to the strategy.
    import inspect

    src = inspect.getsource(CallSugar._build)
    body = [
        ln.strip()
        for ln in src.splitlines()
        if ln.strip() and not ln.strip().startswith(("def", "#"))
    ]
    assert body == ["return self.strategy.emit(self, ctx)"], body


# --- the over-claim is fixed: every formerly-panicking shape routes to CallSugar ---------


@pytest.mark.parametrize(
    "expr", ["np.divide(6, 2)", "np.add(2, 3)", "numpy_testing.assert_equal(a, b)"]
)
def test_unresolved_call_builds_a_callsugar_with_factory_gap_strategy_not_a_crash(expr):
    body, _ = _build(expr)
    assert isinstance(body.sugar, CallSugar)
    assert isinstance(body.sugar.strategy, FactoryGapStrategy)


def test_addsugar_no_longer_claims_np_add():
    # `np.add(2, 3)` is a method call named "add" with TWO args -- it used to be grabbed
    # by AddSugar (method-name only) and TypeError in build. Tightened to arity 1, it now
    # falls through to the CallSugar fallback.
    body, _ = _build("np.add(2, 3)")
    assert isinstance(body.sugar, CallSugar)


def test_import_bound_external_call_builds_bridge_strategy():
    ctx = FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        import_aliases={"math": "math"},
    )
    body = ctx.build_body(_frag("math.sqrt(4)"), SugarRole.TERM)
    assert isinstance(body.sugar, CallSugar)
    assert isinstance(body.sugar.strategy, ExternalBridgeStrategy)
    assert body.sugar.strategy.target_name == "math.sqrt"


# --- FactoryGapStrategy emits a LOUD typed effect, never a silent lift --------------------


def test_factory_gap_strategy_emits_a_named_factory_gap_effect_on_reduce():
    body, ctx = _build("np.divide(6, 2)")
    effect = _reduce_gap_effect(body, ctx)
    assert effect.observed == "call-method:divide"
    assert "divide" in effect.fix


def test_factory_gap_strategy_classifies_builtin_call_frontier():
    # `sum` is a coordinate OpaqueOpCallsite now (#3918) — not a call-builtin gap.
    # Probe a still-uncoordinated builtin frontier for the gap classification law.
    body, ctx = _build("open(path)")

    effect = _reduce_gap_effect(body, ctx)

    assert effect.observed == "call-builtin:open"
    assert effect.fix == (
        "add builtin call sugar for `open`, resolve a local body, "
        "link an imported .proof, or emit a real effect"
    )


def test_builtin_sum_is_coordinate_opaque_op_not_call_builtin_gap():
    """#3918: sum(...) mints call:sum coordinate, not FactoryGap call-builtin:sum."""
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
    from sugar_lift_py_tests.outcome import Complete

    body, ctx = _build("sum([1, 2])")
    outcome = body.reduce(ctx)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, OpaqueOpCallsite)
    assert outcome.value.callee == "sum"
    assert outcome.value.computed is not None  # concrete list → computed sum


def test_factory_gap_strategy_classifies_method_call_frontier():
    body, ctx = _build("buffer.decode()")

    effect = _reduce_gap_effect(body, ctx)

    assert effect.observed == "call-method:decode"
    assert effect.fix == (
        "add receiver-dispatched method sugar for `decode`, resolve a local body, "
        "link an imported .proof, or emit a real effect"
    )


def test_factory_gap_strategy_classifies_unresolved_local_call_frontier():
    body, ctx = _build("my_int16(3)")

    effect = _reduce_gap_effect(body, ctx)

    assert effect.observed == "call-local:my_int16"
    assert effect.fix == (
        "resolve local call `my_int16` to a body, link an imported .proof, "
        "add sugar, or emit a real effect"
    )


def test_zero_arg_local_call_with_unlifted_body_emits_named_effect_not_raw_typeerror():
    module = ast.parse("def f():\n    if True:\n        return 1\nf()")
    function = module.body[0]
    call = module.body[1].value
    ctx = FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        name_resolver={"f": function},
    )

    body = ctx.build_body(call, SugarRole.TERM)
    assert isinstance(body.sugar, CallSugar)
    assert isinstance(body.sugar.strategy, FactoryGapStrategy)

    effect = _reduce_gap_effect(body, ctx)

    assert effect.observed == "call-local:f"
    assert effect.requested == "FunctionBodyConstraint"
