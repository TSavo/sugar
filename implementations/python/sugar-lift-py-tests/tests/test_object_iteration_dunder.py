from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import ArrayLiteral, BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.operations.sequence_projection_operation import (
    SequenceProjectionOperation,
)
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


def _reduce_function_return(source: str, name: str):
    module = ast.parse(source)
    ctx = _ctx_for_module(source)
    function = next(
        stmt
        for stmt in module.body
        if isinstance(stmt, ast.FunctionDef) and stmt.name == name
    )
    block = ctx.build_body(Block.of(function.body), SugarRole.STATEMENT)
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())
    value = complete_value(
        block.reduce(reduce_ctx),
        owner="object iteration dunder block",
    )
    assert isinstance(value, BlockValue)
    assert len(value.statements) == 1
    returned = value.statements[0]
    assert isinstance(returned, ReturnValue)
    return returned.value, reduce_ctx.operation_log


def test_object_iter_returning_list_projects_for_unpack() -> None:
    source = """\
class Iterable:
    def __iter__(self):
        return [1, 2]

def t():
    first, second = Iterable()
    return second
"""

    value, operation_log = _reduce_function_return(source, "t")

    assert value == TermValue(2)
    assert operation_log == [
        (
            "TupleUnpackProjection",
            "project_sequence_with",
            "SequenceProjectionOperation",
        ),
        (
            "TupleUnpackProjection.__iter__",
            "project_sequence_with",
            "SequenceProjectionOperation",
        ),
    ]


def test_temporal_object_iter_binding_can_drive_array_index_value_demand() -> None:
    source = """\
class Iterable:
    def __iter__(self):
        return [0, 2]

def t():
    it = Iterable()
    first, second = it
    return [10, 20, 30][second]
"""

    value, _operation_log = _reduce_function_return(source, "t")

    assert value == TermValue(30)


def test_object_iter_returning_tuple_projects_for_unpack() -> None:
    source = """\
class Iterable:
    def __iter__(self):
        return (3, 4)

def t():
    first, second = Iterable()
    return first
"""

    value, _operation_log = _reduce_function_return(source, "t")

    assert value == TermValue(3)


def test_existing_array_and_tuple_projection_stays_unchanged() -> None:
    ctx = ReduceContext(temporal=TemporalContext.empty())
    operation = SequenceProjectionOperation(
        index=1,
        owner="iteration guard",
        blame="t.py:1:0",
    )

    array_value = complete_value(
        ArrayLiteral((TermValue(1), TermValue(2))).project_sequence_with(
            operation,
            ctx,
        ),
        owner="array projection guard",
    )
    tuple_value = complete_value(
        TupleLiteralValue((TermValue(3), TermValue(4))).project_sequence_with(
            operation,
            ctx,
        ),
        owner="tuple projection guard",
    )

    assert array_value == TermValue(2)
    assert tuple_value == TermValue(4)
