"""`1 == 1` lifts end to end: the compare folds to the True literal, which stands on the
bool floor by construction, so `if 1 == 1: pass` reduces to the then-branch -- no
BoolValue, no bool-floor step. A comparison we have NOT lifted (`<`) still panics, and
the panic is a FactoryPanic that ordinary `except Exception:` cannot swallow."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def _if(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    return build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx).sugar, ctx


def test_equality_condition_folds_to_true_and_takes_the_then_branch() -> None:
    sugar, ctx = _if("if 1 == 1:\n    pass")

    # the compare folds to the True literal -- it IS the standing, no field
    assert isinstance(sugar.condition.reduce(ctx).value, TrueBoolLiteralSugar)

    # so the if lifts to the then-branch, no panic
    assert isinstance(sugar.desugar(ctx), Complete)


def test_inequality_condition_folds_to_false_and_emits_nothing() -> None:
    sugar, ctx = _if("if 1 == 2:\n    pass")

    # the compare folds to the False literal
    assert isinstance(sugar.condition.reduce(ctx).value, FalseBoolLiteralSugar)

    # False with no else emits nothing -- an empty block, no constraint on the universe
    out = sugar.desugar(ctx)
    assert isinstance(out, Complete)
    assert out.value.statements == ()


def test_unlifted_comparison_panics() -> None:
    # `<` is not lifted -- CompareOpSugar owns only ==/!= -- so nothing owns the Compare
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("if 1 < 1:\n    pass").body[0]
    try:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    except FactoryPanic as panic:
        assert panic.info.fix
        return
    raise AssertionError("`1 < 1` built cleanly -- `<` is not lifted, it must panic")


def test_ordinary_except_does_not_swallow_the_panic() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("if 1 < 1:\n    pass").body[0]
    try:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    except Exception:  # noqa: BLE001 -- must never fire; the panic is a BaseException
        raise AssertionError("except Exception swallowed the panic -- side door!")
    except FactoryPanic:
        return
    raise AssertionError("`1 < 1` built cleanly -- it must panic")
