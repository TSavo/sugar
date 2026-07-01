from __future__ import annotations

import ast
from dataclasses import replace

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BlockValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.tuple_unpack_projection import TupleUnpackProjection
from sugar_lift_py_tests.temporal import TemporalContext


def test_tuple_unpack_assign_binds_projection_from_symbolic_rhs() -> None:
    assert compose_block(
        "    x, y = values\n    return y\n",
        binds={"values": SymbolicValue(make_var("values"))},
    ) == BlockValue(
        (ReturnValue(SymbolicValue(ctor("py.unpack", [make_var("values"), num(1)]))),)
    )


def test_list_unpack_assign_binds_projection_from_symbolic_rhs() -> None:
    assert compose_block(
        "    [x, y] = values\n    return x\n",
        binds={"values": SymbolicValue(make_var("values"))},
    ) == BlockValue(
        (ReturnValue(SymbolicValue(ctor("py.unpack", [make_var("values"), num(0)]))),)
    )


def test_tuple_unpack_assign_selects_dedicated_sugar_for_non_literal_rhs() -> None:
    result = build_node(
        ast.parse("x, y = values").body[0],
        filename="f.py",
        role=SugarRole.STATEMENT,
    )

    assert result.audit_row.selected == "TupleUnpackAssignSugar"


def _compose_block_with_log(body_src: str, binds: dict | None = None):
    fn = ast.parse(f"def f(x):\n{body_src}").body[0]
    block = Block.of(fn.body)
    build_ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    temporal = TemporalContext.empty()
    if binds:
        for name, value in binds.items():
            temporal = temporal.bind_value(name, value)
        build_ctx = replace(build_ctx, temporal=temporal)
    result = build_node(
        block,
        filename="f.py",
        role=SugarRole.STATEMENT,
        ctx=build_ctx,
    )
    reduce_ctx = ReduceContext(temporal=temporal)
    value = complete_value(result.sugar.desugar(reduce_ctx), owner="tuple/list block")
    return value, reduce_ctx.operation_log


def test_tuple_assign_projects_literal_tuple_through_floor_operation_log() -> None:
    value, operation_log = _compose_block_with_log("    x, y = 1, 2\n    return y\n")

    assert value == BlockValue((ReturnValue(TermValue(2)),))
    assert operation_log == [
        (
            "TupleLiteralSugar",
            "construct_sequence_with",
            "SequenceConstructionOperation",
        ),
        (
            "TupleUnpackProjection",
            "project_sequence_with",
            "SequenceProjectionOperation",
        ),
    ]


def test_list_unpack_projects_array_floor_through_floor_operation_log() -> None:
    value, operation_log = _compose_block_with_log(
        "    x, y = values\n    return x\n",
        binds={"values": ArrayLiteral((TermValue(1), TermValue(2)))},
    )

    assert value == BlockValue((ReturnValue(TermValue(1)),))
    assert operation_log == [
        (
            "TupleUnpackProjection",
            "project_sequence_with",
            "SequenceProjectionOperation",
        )
    ]


def test_tuple_unpack_projection_unsupported_floor_names_floor_gap() -> None:
    build_ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    body = build_ctx.build_body(ast.parse("10", mode="eval").body, SugarRole.TERM)
    projection = TupleUnpackProjection(body, 0, blame="f.py:1:0")
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())

    with pytest.raises(FactoryGap) as raised:
        projection.desugar(reduce_ctx)

    assert raised.value.info == {
        "owner": "TupleUnpackProjection",
        "blame": "f.py:1:0",
        "observed": "TermValue",
        "requested": "project_sequence_with",
        "fix": "add project_sequence_with to TermValue or emit a real effect",
    }
