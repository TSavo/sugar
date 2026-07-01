"""CallSugar -- the dumb call shell + its strategies (CALLSUGAR_REFACTOR_GOAL.md).

Step 2 scope: the dumb shell (owns=shape, build=router, desugar=delegate) and the real
RefuseStrategy. BridgeStrategy / AssertionFactStrategy (the in-body EUF bridge + dig, and
the sworn fact) land in Steps 3-4 with their own tests. No NotImplementedError stubs here.
"""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.build import FactoryBuildContext, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.sugar.call_sugar import (
    CallSugar,
    ExternalBridgeStrategy,
    RefuseStrategy,
)


def _frag(expr: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body, "t.py")


def _build(expr: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    return ctx.build_body(_frag(expr), SugarRole.TERM), ctx


# --- owns is SHAPE ONLY -----------------------------------------------------------------


def test_owns_is_shape_only_a_call_yes_a_non_call_no():
    assert CallSugar.owns(_frag("f(1)")) is True
    assert CallSugar.owns(_frag("5")) is False
    assert CallSugar.owns(_frag("x + 1")) is False


def test_desugar_is_a_single_delegation_no_context_branch():
    # structural: desugar's only statement delegates to the strategy.
    import inspect

    src = inspect.getsource(CallSugar.desugar)
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
def test_unresolved_call_builds_a_callsugar_with_refusestrategy_not_a_crash(expr):
    body, _ = _build(expr)
    assert isinstance(body.sugar, CallSugar)
    assert isinstance(body.sugar.strategy, RefuseStrategy)


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


# --- RefuseStrategy refuses LOUD and NAMED, never a silent lift --------------------------


def test_refuse_strategy_raises_a_named_factory_gap_on_reduce():
    body, ctx = _build("np.divide(6, 2)")
    with pytest.raises(FactoryGap) as raised:
        body.reduce(ctx)
    assert raised.value.info["observed"] == "call-method:divide"
    assert "divide" in raised.value.info["fix"]


def test_refuse_strategy_classifies_builtin_call_frontier():
    body, ctx = _build("hash(value)")

    with pytest.raises(FactoryGap) as raised:
        body.reduce(ctx)

    assert raised.value.info["observed"] == "call-builtin:hash"
    assert raised.value.info["fix"] == (
        "add builtin call sugar for `hash`, resolve a local body, "
        "link an imported .proof, or emit a real effect"
    )


def test_refuse_strategy_classifies_method_call_frontier():
    body, ctx = _build("buffer.decode()")

    with pytest.raises(FactoryGap) as raised:
        body.reduce(ctx)

    assert raised.value.info["observed"] == "call-method:decode"
    assert raised.value.info["fix"] == (
        "add receiver-dispatched method sugar for `decode`, resolve a local body, "
        "link an imported .proof, or emit a real effect"
    )


def test_refuse_strategy_classifies_unresolved_local_call_frontier():
    body, ctx = _build("my_int16(3)")

    with pytest.raises(FactoryGap) as raised:
        body.reduce(ctx)

    assert raised.value.info["observed"] == "call-local:my_int16"
    assert raised.value.info["fix"] == (
        "resolve local call `my_int16` to a body, link an imported .proof, "
        "add sugar, or emit a real effect"
    )


def test_zero_arg_local_call_with_unlifted_body_refuses_named_not_raw_typeerror():
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
    assert isinstance(body.sugar.strategy, RefuseStrategy)

    with pytest.raises(FactoryGap) as raised:
        body.reduce(ctx)

    assert raised.value.info["observed"] == "call-local:f"
    assert raised.value.info["requested"] == "FunctionBodyConstraint"
