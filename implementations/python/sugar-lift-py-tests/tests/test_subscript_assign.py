from __future__ import annotations

import ast

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar_body import SugarBody


def _build(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    return build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx).sugar


def test_subscript_assign_rebinds_concrete_list_post_state() -> None:
    assert compose_block(
        "    xs = [1, 2, 3]\n    xs[1] = 9\n    return xs[1]\n"
    ) == BlockValue((ReturnValue(TermValue(9)),))


def test_subscript_assign_rebinds_concrete_dict_post_state() -> None:
    assert compose_block(
        '    d = {"k": 1}\n    d["k"] = 9\n    return d["k"]\n'
    ) == BlockValue((ReturnValue(TermValue(9)),))


def test_symbolic_subscript_assign_is_a_typed_store_effect() -> None:
    outcome = compose_block(
        '    d["k"] = 9\n', binds={"d": SymbolicValue(make_var("d"))}
    )

    assert isinstance(outcome, BlockValue)
    assert len(outcome.statements) == 1
    assert isinstance(outcome.statements[0], Incomplete)
    assert isinstance(outcome.statements[0].effect, SubscriptStoreRuntimeEffect)


def test_slice_subscript_assign_stays_a_loud_factory_gap() -> None:
    with pytest.raises(FactoryPanic):
        _build("xs[1:2] = [9]\n")


def test_unliftable_subscript_receiver_reaches_none_arm_loudly() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("def f():\n    (yield 1)[0] = 9\n").body[0].body[0]

    with pytest.raises(FactoryPanic):
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)


def test_subscript_assign_carries_factory_built_children() -> None:
    sugar = _build("xs[1] = 9\n")

    assert type(sugar).__name__ == "SubscriptAssignSugar"
    assert isinstance(sugar.receiver, SugarBody)
    assert isinstance(sugar.index, SugarBody)
    assert isinstance(sugar.value, SugarBody)
    assert sugar.walk_children() == (sugar.receiver, sugar.index, sugar.value)
