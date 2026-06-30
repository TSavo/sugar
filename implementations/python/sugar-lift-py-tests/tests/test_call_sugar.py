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
from sugar_lift_py_tests.sugar.call_sugar import CallSugar, RefuseStrategy


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
    body = [ln.strip() for ln in src.splitlines() if ln.strip() and not ln.strip().startswith(("def", "#"))]
    assert body == ["return self.strategy.emit(self, ctx)"], body


# --- the over-claim is fixed: every formerly-panicking shape routes to CallSugar ---------

@pytest.mark.parametrize("expr", ["np.divide(6, 2)", "np.add(2, 3)", "numpy_testing.assert_equal(a, b)"])
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


# --- RefuseStrategy refuses LOUD and NAMED, never a silent lift --------------------------

def test_refuse_strategy_raises_a_named_factory_gap_on_reduce():
    body, ctx = _build("np.divide(6, 2)")
    with pytest.raises(FactoryGap) as raised:
        body.reduce(ctx)
    assert raised.value.info["observed"] == "Call"
    assert "divide" in raised.value.info["fix"]
