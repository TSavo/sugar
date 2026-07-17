from __future__ import annotations

import ast

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    ListValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, make_var
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


def test_call_result_subscript_assign_is_a_coordinate_carrying_store_effect() -> None:
    outcome = compose_block('    make()["k"] = 9\n')

    assert isinstance(outcome, BlockValue)
    assert len(outcome.statements) == 1
    incomplete = outcome.statements[0]
    assert isinstance(incomplete, Incomplete)
    assert isinstance(incomplete.effect, SubscriptStoreRuntimeEffect)
    assert "call:make" in incomplete.effect.reason
    assert "_ConstStr(value='k'" in incomplete.effect.reason
    assert "_ConstInt(value=9" in incomplete.effect.reason


def test_callsite_store_reason_never_renders_floor_object_graphs() -> None:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    class CoordinateOnlyValue(TermValue):
        def __repr__(self) -> str:
            raise AssertionError("store effects must cite terms, not object repr")

    receiver = CallSiteValue(
        target_name="make",
        arg_values=(),
        parameters=(),
        term=ctor("call:make", []),
        body=None,
    )
    site = SourceFragment.from_source("make()[1] = 2\n", "t.py").statements()[0]

    outcome = receiver.setitem(CoordinateOnlyValue(1), CoordinateOnlyValue(2), site)

    assert isinstance(outcome, Incomplete)
    assert "_ConstInt(value=1" in outcome.reason
    assert "_ConstInt(value=2" in outcome.reason


def test_callsite_setitem_arm_does_not_replace_concrete_list_post_state() -> None:
    receiver = ListValue((TermValue(1), TermValue(2)))

    outcome = receiver.setitem(TermValue(0), TermValue(9), "t.py:1:0")

    assert outcome.value == ListValue((TermValue(9), TermValue(2)))


def test_runtime_store_receivers_own_explicit_setitem_arms() -> None:
    assert "setitem" in CallSiteValue.__dict__
    assert "setitem" in SymbolicValue.__dict__


def test_slice_subscript_assign_is_owned_and_reaches_store_floor() -> None:
    sugar = _build("xs[1:2] = [9]\n")

    assert type(sugar).__name__ == "SubscriptAssignSugar"
    assert type(sugar.index.sugar).__name__ == "SliceSugar"


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
