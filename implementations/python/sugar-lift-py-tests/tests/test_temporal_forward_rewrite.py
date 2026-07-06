from __future__ import annotations

import ast
from typing import ClassVar

import pytest

from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import ArrayLiteral, BuilderState, TermValue
from sugar_lift_py_tests.operations import (
    AddOperation,
    MapOperation,
    MaterializeOperation,
    perform_operation,
)
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.add_sugar import ADD_CLAIM, AddSugar
from sugar_lift_py_tests.sugar.array_literal_sugar import (
    ARRAY_LITERAL_CLAIM,
    ArrayLiteralSugar,
)
from sugar_lift_py_tests.sugar.binop_sugar import BINOP_CLAIM, BinOpSugar
from sugar_lift_py_tests.sugar.builder_ctor_sugar import (
    BUILDER_CTOR_CLAIM,
    BuilderCtorSugar,
)
from sugar_lift_py_tests.sugar.lambda_sugar import LAMBDA_CLAIM, LambdaSugar
from sugar_lift_py_tests.sugar.map_sugar import MAP_CLAIM, MapSugar
from sugar_lift_py_tests.sugar.name_sugar import NAME_CLAIM, NameSugar
from sugar_lift_py_tests.sugar.primitive_literal_sugar import PRIMITIVE_LITERAL_CLAIM
from sugar_lift_py_tests.sugar.to_list_sugar import TO_LIST_CLAIM, ToListSugar
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import (
    AddAssignRewriteOperation,
    TemporalContext,
    bind_temporal,
    rewrite_temporal,
)

SOURCE = """
n = 10
n += 1
out = Builder([1, 2, 3]).map(lambda x: x + 2).add(n).to_list()
assert out == [14, 15, 16]
"""


class _UnknownFluentOperation:
    method_name: ClassVar[str] = "unknown_with"


def _temporal_catalog() -> SugarCatalog:
    return SugarCatalog(
        [
            TO_LIST_CLAIM,
            ADD_CLAIM,
            MAP_CLAIM,
            BUILDER_CTOR_CLAIM,
            LAMBDA_CLAIM,
            BINOP_CLAIM,
            NAME_CLAIM,
            ARRAY_LITERAL_CLAIM,
            PRIMITIVE_LITERAL_CLAIM,
        ]
    )


def _out_rhs() -> ast.AST:
    module = ast.parse(SOURCE)
    statement = module.body[2]
    assert isinstance(statement, ast.Assign)
    return statement.value


def test_fluent_builder_constructs_bodies_then_rewrites_forward():
    setup_ctx = ReduceContext(temporal=TemporalContext.empty())
    setup_ctx = bind_temporal(
        setup_ctx,
        "n",
        TermValue(10),
        owner="temporal builder setup",
        blame="builder.py:2:0",
    )
    setup_ctx = rewrite_temporal(
        setup_ctx,
        AddAssignRewriteOperation(
            name="n",
            value=TermValue(1),
            owner="temporal builder setup",
            blame="builder.py:3:0",
        ),
        owner="temporal builder setup",
        blame="builder.py:3:0",
    )
    temporal = setup_ctx.temporal
    build_ctx = FactoryBuildContext(
        filename="builder.py",
        catalog=_temporal_catalog(),
        temporal=temporal,
    )

    body = build_ctx.build_body(_out_rhs(), SugarRole.TERM)

    assert isinstance(body, SugarBody)
    assert isinstance(body.sugar, ToListSugar)
    assert isinstance(body.sugar.receiver, SugarBody)

    add = body.sugar.receiver.sugar
    assert isinstance(add, AddSugar)
    assert isinstance(add.receiver, SugarBody)
    assert isinstance(add.operand, SugarBody)
    assert isinstance(add.operand.sugar, NameSugar)
    assert add.operand.sugar.identifier == "n"

    mapped = add.receiver.sugar
    assert isinstance(mapped, MapSugar)
    assert isinstance(mapped.receiver, SugarBody)
    assert isinstance(mapped.mapper, SugarBody)

    builder = mapped.receiver.sugar
    assert isinstance(builder, BuilderCtorSugar)
    assert isinstance(builder.items, SugarBody)
    assert isinstance(builder.items.sugar, ArrayLiteralSugar)

    mapper = mapped.mapper.sugar
    assert isinstance(mapper, LambdaSugar)
    assert isinstance(mapper.body, SugarBody)
    assert isinstance(mapper.body.sugar, BinOpSugar)
    assert isinstance(mapper.body.sugar.left, SugarBody)
    assert isinstance(mapper.body.sugar.right, SugarBody)

    assert temporal.value_for("n") == TermValue(11)

    reduce_ctx = ReduceContext(temporal=temporal)
    outcome = body.reduce(reduce_ctx)
    value = complete_value(outcome, owner="temporal fluent builder")

    assert value == ArrayLiteral((TermValue(14), TermValue(15), TermValue(16)))
    assert len(value.items) == 3
    assert [item.value for item in value.items] == [14, 15, 16]
    assert reduce_ctx.operation_log == [
        ("MapSugar", "map_with", "MapOperation"),
        ("LambdaCallable", "bind_with", "BindValueOperation"),
        ("BinOpSugar", "binary_operator_with", "BinaryOperatorOperation"),
        ("LambdaCallable", "bind_with", "BindValueOperation"),
        ("BinOpSugar", "binary_operator_with", "BinaryOperatorOperation"),
        ("LambdaCallable", "bind_with", "BindValueOperation"),
        ("BinOpSugar", "binary_operator_with", "BinaryOperatorOperation"),
        ("AddSugar", "add_with", "AddOperation"),
        ("ToListSugar", "materialize_with", "MaterializeOperation"),
    ]


def test_temporal_add_assign_rewrite_dispatches_through_the_bound_floor():
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())
    reduce_ctx = bind_temporal(
        reduce_ctx,
        "n",
        TermValue(10),
        owner="TemporalContext",
        blame="builder.py:2:0",
    )

    rewritten = rewrite_temporal(
        reduce_ctx,
        AddAssignRewriteOperation(
            name="n",
            value=TermValue(1),
            owner="TemporalContext",
            blame="builder.py:3:0",
        ),
        owner="TemporalContext",
        blame="builder.py:3:0",
    )

    assert rewritten.temporal.value_for("n") == TermValue(11)
    assert reduce_ctx.operation_log == [
        ("TemporalContext", "bind_with", "BindValueOperation"),
        ("TemporalContext", "rewrite_with", "AddAssignRewriteOperation"),
        ("TemporalContext", "add_with", "AddOperation"),
    ]


def test_temporal_add_assign_bad_operand_names_the_floor_gap():
    reduce_ctx = ReduceContext(temporal=TemporalContext.empty())
    reduce_ctx = bind_temporal(
        reduce_ctx,
        "n",
        TermValue(10),
        owner="TemporalContext",
        blame="builder.py:2:0",
    )

    with pytest.raises(FactoryGap) as gap:
        rewrite_temporal(
            reduce_ctx,
            AddAssignRewriteOperation(
                name="n",
                value=ArrayLiteral((TermValue(1),)),
                owner="TemporalContext",
                blame="builder.py:3:0",
            ),
            owner="TemporalContext",
            blame="builder.py:3:0",
        )

        assert gap.value.info.to_json() == {
            "owner": "TemporalContext",
            "blame": "builder.py:3:0",
            "observed": "TermValue+ArrayLiteral",
            "requested": "add operand floor",
            "fix": "add AddOperation support for TermValue with ArrayLiteral",
            "gap_kind": "Floor",
            "gap_locus": "Construction",
        }


def test_unknown_fluent_receiver_mutation_is_a_named_floor_gap():
    ctx = ReduceContext(temporal=TemporalContext.empty())
    receiver = BuilderState(ArrayLiteral((TermValue(1),)))

    with pytest.raises(FactoryGap) as gap:
        perform_operation(
            owner="UnknownFluentSugar",
            blame="builder.py:1:0",
            receiver=receiver,
            operation=_UnknownFluentOperation(),
            ctx=ctx,
        )

    message = str(gap.value)
    assert message.startswith("write more Operation for this method_name")
    assert "owner=UnknownFluentSugar" in message
    assert "observed=_UnknownFluentOperation" in message
    assert "requested=unknown_with" in message
