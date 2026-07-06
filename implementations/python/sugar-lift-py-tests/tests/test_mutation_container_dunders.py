from __future__ import annotations

import ast

import pytest
from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BlockValue,
    CallSiteValue,
    ReturnValue,
)
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.ir import ctor, num, str_const
from sugar_lift_py_tests.operations import (
    DelItemOperation,
    DictMissingOperation,
    SetItemOperation,
    SubscriptOperation,
    perform_operation,
)
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.temporal import TemporalContext


def _ctx_for_source(source: str) -> tuple[SourceFragment, FactoryBuildContext]:
    root = SourceFragment.from_source(source, "t.py")
    resolver = {}
    for fragment in _top_level_fragments(root):
        if fragment.observed == "ClassDef":
            resolver[fragment.class_name()] = fragment.node
        if fragment.observed == "FunctionDef":
            resolver[fragment.function_name()] = fragment.node
    catalog = default_catalog()
    return root, FactoryBuildContext(
        filename="t.py",
        catalog=catalog,
        name_resolver=resolver,
    )


def _top_level(root: SourceFragment, name: str) -> SourceFragment:
    for fragment in _top_level_fragments(root):
        if fragment.observed == "ClassDef" and fragment.class_name() == name:
            return fragment
        if fragment.observed == "FunctionDef" and fragment.function_name() == name:
            return fragment
    raise AssertionError(f"missing top-level fragment {name!r}")


def _top_level_fragments(root: SourceFragment) -> list[SourceFragment]:
    fragments = root.fragments()
    if len(fragments) == 1 and fragments[0].observed == "Block":
        return fragments[0].fragments()
    return fragments


def _reduce_expr(source: str, expr: str):
    full_source = f"{source.rstrip()}\n\ndef _probe():\n    return {expr}\n"
    root, ctx = _ctx_for_source(full_source)
    function = _top_level(root, "_probe")
    statement = function.function_body()[0]
    value = statement.return_value()
    assert value is not None
    body = ctx.build_body(value, SugarRole.TERM)
    return complete_value(
        body.reduce(ctx),
        owner="mutation container dunder expression",
    )


def _reduce_function_body(source: str, name: str) -> tuple[BlockValue, list]:
    module = ast.parse(source)
    _root, ctx = _ctx_for_source(source)
    function = next(
        stmt
        for stmt in module.body
        if isinstance(stmt, ast.FunctionDef) and stmt.name == name
    )
    block = ctx.build_body(Block.of(function.body), SugarRole.STATEMENT)
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())
    value = complete_value(
        block.reduce(reduce_ctx),
        owner="mutation container dunder block",
    )
    assert isinstance(value, BlockValue)
    return value, reduce_ctx.operation_log


def _project_array_index(index) -> TermValue:
    value = complete_value(
        ArrayLiteral((TermValue(10), TermValue(20), TermValue(30))).subscript_with(
            SubscriptOperation(
                index=index,
                owner="mutation container dunder value demand",
                blame="t.py:1:0",
            ),
            ReduceContext(temporal=TemporalContext.empty()),
        ),
        owner="mutation container dunder value demand",
    )
    assert isinstance(value, TermValue)
    return value


def _object_identity(class_name: str, blame: str):
    return ctor("py.object.identity", [str_const(class_name), str_const(blame)])


def test_reversed_builtin_projects_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __reversed__(self):
        return 1
"""

    value = _reduce_expr(source, "reversed(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__reversed__"
    assert fol(floor_to_term(value, owner="reversed dunder bridge")) == fol(
        ctor("call:Box.__reversed__", [_object_identity("Box", "t.py:6:20")])
    )


def test_reversed_dunder_can_drive_array_index_value_demand() -> None:
    source = """\
class Box:
    def __reversed__(self):
        return 1
"""

    value = _reduce_expr(source, "[10, 20, 30][reversed(Box())]")

    assert value == TermValue(20)


def test_setitem_operation_projects_to_dunder_method_and_value_demand() -> None:
    source = """\
class Box:
    def __setitem__(self, key, value):
        return value
"""
    receiver = _reduce_expr(source, "Box()")
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())

    value = complete_value(
        perform_operation(
            owner="SubscriptAssignSugar",
            blame="t.py:6:4",
            receiver=receiver,
            operation=SetItemOperation(
                index=TermValue(0),
                value=TermValue(1),
                owner="SubscriptAssignSugar",
                blame="t.py:6:4",
            ),
            ctx=reduce_ctx,
        ),
        owner="setitem dunder operation",
    )

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__setitem__"
    assert fol(floor_to_term(value, owner="setitem dunder bridge")) == fol(
        ctor(
            "call:Box.__setitem__",
            [
                _object_identity("Box", "t.py:6:11"),
                num(0),
                num(1),
            ],
        )
    )
    assert _project_array_index(value) == TermValue(20)
    assert reduce_ctx.operation_log == [
        ("SubscriptAssignSugar", "setitem_with", "SetItemOperation")
    ]


def test_subscript_assignment_statement_dispatches_setitem_and_absorbs_return() -> None:
    source = """\
class Box:
    def __setitem__(self, key, value):
        return value

def t():
    box = Box()
    box[0] = 1
    return 2
"""

    value, operation_log = _reduce_function_body(source, "t")

    assert value == BlockValue((ReturnValue(TermValue(2)),))
    assert operation_log == [
        ("BlockSugar", "bind_with", "BindValueOperation"),
        ("CallSiteValue.force_floor", "curry_with", "CurryArgumentsOperation"),
        ("SubscriptAssignSugar", "setitem_with", "SetItemOperation"),
    ]


def test_subscript_assignment_rebinds_literal_array_post_state() -> None:
    source = """\
def t():
    xs = [1, 2, 3]
    xs[1] = 9
    return xs[1]
"""

    value, operation_log = _reduce_function_body(source, "t")

    assert value == BlockValue((ReturnValue(TermValue(9)),))
    assert operation_log == [
        ("BlockSugar", "bind_with", "BindValueOperation"),
        ("SubscriptAssignSugar", "setitem_with", "SetItemOperation"),
        ("BlockSugar", "bind_with", "BindValueOperation"),
        ("StringSubscriptSugar", "subscript_with", "SubscriptOperation"),
    ]


def test_subscript_delete_statement_dispatches_delitem_and_absorbs_return() -> None:
    source = """\
class Box:
    def __delitem__(self, key):
        return key

def t():
    box = Box()
    del box[0]
    return 1
"""

    value, operation_log = _reduce_function_body(source, "t")

    assert value == BlockValue((ReturnValue(TermValue(1)),))
    assert operation_log == [
        ("BlockSugar", "bind_with", "BindValueOperation"),
        ("CallSiteValue.force_floor", "curry_with", "CurryArgumentsOperation"),
        ("SubscriptDeleteSugar", "delitem_with", "DelItemOperation"),
    ]


def test_subscript_delete_rebinds_literal_array_post_state() -> None:
    source = """\
def t():
    xs = [1, 2, 3]
    del xs[1]
    return xs[1]
"""

    value, operation_log = _reduce_function_body(source, "t")

    assert value == BlockValue((ReturnValue(TermValue(3)),))
    assert operation_log == [
        ("BlockSugar", "bind_with", "BindValueOperation"),
        ("SubscriptDeleteSugar", "delitem_with", "DelItemOperation"),
        ("BlockSugar", "bind_with", "BindValueOperation"),
        ("StringSubscriptSugar", "subscript_with", "SubscriptOperation"),
    ]


def test_subscript_delete_without_delitem_is_a_loud_floor_gap() -> None:
    source = """\
class Box:
    pass

def t():
    box = Box()
    del box[0]
"""

    with pytest.raises(FactoryGap) as raised:
        _reduce_function_body(source, "t")

    assert raised.value.info.to_json()["owner"] == "SubscriptDeleteSugar"
    assert raised.value.info.to_json()["observed"] == "Box.__delitem__"
    assert raised.value.info.to_json()["requested"] == "constructor-bound method"


def test_missing_operation_projects_to_dict_key_miss_dunder_and_value_demand() -> None:
    source = """\
class Defaults:
    def __missing__(self, key):
        return 1
"""
    receiver = _reduce_expr(source, "Defaults()")
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())

    value = complete_value(
        perform_operation(
            owner="DictMissingOperation",
            blame="t.py:6:4",
            receiver=receiver,
            operation=DictMissingOperation(
                key=TermValue(99),
                owner="DictMissingOperation",
                blame="t.py:6:4",
            ),
            ctx=reduce_ctx,
        ),
        owner="missing dunder operation",
    )

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Defaults.__missing__"
    assert fol(floor_to_term(value, owner="missing dunder bridge")) == fol(
        ctor(
            "call:Defaults.__missing__",
            [
                _object_identity("Defaults", "t.py:6:11"),
                num(99),
            ],
        )
    )
    assert _project_array_index(value) == TermValue(20)
    assert reduce_ctx.operation_log == [
        ("DictMissingOperation", "missing_with", "DictMissingOperation")
    ]


def test_missing_operation_on_unsupported_receiver_is_a_loud_floor_gap() -> None:
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())

    with pytest.raises(FactoryGap) as raised:
        perform_operation(
            owner="DictMissingOperation",
            blame="t.py:1:0",
            receiver=TermValue(0),
            operation=DictMissingOperation(
                key=TermValue(99),
                owner="DictMissingOperation",
                blame="t.py:1:0",
            ),
            ctx=reduce_ctx,
        )

    assert raised.value.info.to_json()["owner"] == "DictMissingOperation"
    assert raised.value.info.to_json()["observed"] == "TermValue"
    assert raised.value.info.to_json()["requested"] == "missing_with"
    assert (
        raised.value.info.to_json()["fix"]
        == "add missing_with to TermValue or emit a real effect"
    )
