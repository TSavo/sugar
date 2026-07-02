from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def _ctx_for_module(source: str) -> FactoryBuildContext:
    module = ast.parse(source)
    resolver = {
        stmt.name: stmt
        for stmt in module.body
        if isinstance(stmt, (ast.FunctionDef, ast.ClassDef))
    }
    return FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        name_resolver=resolver,
    )


def _returned_value(source: str, name: str):
    module = ast.parse(source)
    ctx = _ctx_for_module(source)
    function = next(
        stmt
        for stmt in module.body
        if isinstance(stmt, ast.FunctionDef) and stmt.name == name
    )
    block = ctx.build_body(Block.of(function.body), SugarRole.STATEMENT)
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())
    outcome = block.reduce(reduce_ctx)
    value = complete_value(outcome, owner="context manager dunder block")
    assert isinstance(value, BlockValue)
    assert len(value.statements) == 1
    returned = value.statements[0]
    assert isinstance(returned, ReturnValue)
    return returned.value, reduce_ctx.operation_log


def test_with_context_manager_enter_slot_drives_body_value_demand() -> None:
    source = """\
class Manager:
    def __enter__(self):
        return 1

    def __exit__(self, exc_type, exc, tb):
        return False

def t():
    with Manager() as index:
        return [10, 20, 30][index]
"""

    value, operation_log = _returned_value(source, "t")

    assert value == TermValue(20)
    assert operation_log[-5:] == [
        ("WithSugar", "context_manager_with", "ContextManagerOperation"),
        (
            "CallSiteValue.force_floor",
            "curry_with",
            "CurryArgumentsOperation",
        ),
        ("WithSugar", "bind_with", "BindValueOperation"),
        ("StringSubscriptSugar", "subscript_with", "SubscriptOperation"),
        (
            "CallSiteValue.force_floor",
            "curry_with",
            "CurryArgumentsOperation",
        ),
    ]


def test_with_context_manager_exit_slot_is_forced_after_body() -> None:
    source = """\
class Manager:
    def __enter__(self):
        return 0

    def __exit__(self, exc_type, exc, tb):
        return 2

def t():
    with Manager() as index:
        return [10, 20, 30][index]
"""

    value, operation_log = _returned_value(source, "t")

    assert value == TermValue(10)
    assert operation_log[-1] == (
        "CallSiteValue.force_floor",
        "curry_with",
        "CurryArgumentsOperation",
    )
