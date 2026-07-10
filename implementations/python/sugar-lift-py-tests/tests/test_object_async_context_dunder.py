from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import factory_panic
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
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    return FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        name_resolver=resolver,
    )


def _async_function_body(source: str, name: str):
    module = ast.parse(source)
    function = next(
        stmt
        for stmt in module.body
        if isinstance(stmt, ast.AsyncFunctionDef) and stmt.name == name
    )
    ctx = _ctx_for_module(source)
    body = ctx.build_body(Block.of(function.body), SugarRole.STATEMENT)
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())
    return body, reduce_ctx


def _returned_value(source: str, name: str):
    body, reduce_ctx = _async_function_body(source, name)
    value = complete_value(
        body.reduce(reduce_ctx),
        owner="async context dunder block",
    )
    assert isinstance(value, BlockValue)
    assert len(value.statements) == 1
    returned = value.statements[0]
    assert isinstance(returned, ReturnValue)
    return returned.value, reduce_ctx.operation_log


def test_await_unwraps_object_await_dunder_for_value_demand() -> None:
    source = """\
class Awaitable:
    def __await__(self):
        return 2

async def t():
    return [10, 20, 30][await Awaitable()]
"""

    value, operation_log = _returned_value(source, "t")

    assert value == TermValue(30)
    assert ("AwaitSugar", "await_with", "AwaitOperation") in operation_log
    assert (
        "CallSiteValue.force_floor",
        "curry_with",
        "CurryArgumentsOperation",
    ) in operation_log


def test_async_with_enter_slot_drives_body_value_demand() -> None:
    source = """\
class Manager:
    def __aenter__(self):
        return 1

    def __aexit__(self, exc_type, exc, tb):
        return 2

async def t():
    async with Manager() as index:
        return [10, 20, 30][index]
"""

    value, operation_log = _returned_value(source, "t")

    assert value == TermValue(20)
    assert (
        "AsyncWithSugar",
        "async_context_manager_with",
        "AsyncContextManagerOperation",
    ) in operation_log
    assert ("AsyncWithSugar", "bind_with", "BindValueOperation") in operation_log
    assert operation_log[-1] == (
        "CallSiteValue.force_floor",
        "curry_with",
        "CurryArgumentsOperation",
    )


def test_async_for_owns_protocol_and_refuses_missing_stop_floor_loudly() -> None:
    source = """\
class AsyncItems:
    def __aiter__(self):
        return self

    def __anext__(self):
        return 1

async def t():
    async for item in AsyncItems():
        return item
"""
    body, reduce_ctx = _async_function_body(source, "t")

    with pytest.raises(FactoryGap) as exc:
        body.reduce(reduce_ctx)

    assert exc.value.info.to_json()["observed"] == "AsyncFor.__anext__"
    assert exc.value.info.to_json()["requested"] == "async iteration stop floor"
    assert (
        "AsyncForSugar",
        "async_iter_with",
        "AsyncIteratorOperation",
    ) in reduce_ctx.operation_log
    assert (
        "AsyncForSugar.__aiter__",
        "async_next_with",
        "AsyncNextOperation",
    ) in reduce_ctx.operation_log
