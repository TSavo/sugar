from __future__ import annotations

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.temporal import (
    AddAssignRewriteOperation,
    BindValueOperation,
    CurryArgumentsOperation,
    TemporalContext,
    bind_temporal,
    curry_temporal,
    perform_temporal_operation,
    rewrite_temporal,
)


def test_bind_temporal_dispatches_through_temporal_floor() -> None:
    ctx = ReduceContext(temporal=TemporalContext.empty())

    next_ctx = bind_temporal(
        ctx,
        "x",
        TermValue(3),
        owner="test bind",
        blame="t.py:1:0",
    )

    assert next_ctx.temporal.value_for("x") == TermValue(3)
    assert ctx.operation_log == [
        ("test bind", "bind_with", "BindValueOperation"),
    ]


def test_curry_temporal_dispatches_all_arguments_through_temporal_floor() -> None:
    ctx = ReduceContext(temporal=TemporalContext.empty())

    next_ctx = curry_temporal(
        ctx,
        ("x", "y"),
        (TermValue(3), TermValue(4)),
        owner="test curry",
        blame="t.py:1:0",
    )

    assert next_ctx.temporal.value_for("x") == TermValue(3)
    assert next_ctx.temporal.value_for("y") == TermValue(4)
    assert ctx.operation_log == [
        ("test curry", "curry_with", "CurryArgumentsOperation"),
    ]


def test_rewrite_temporal_add_assign_dispatches_to_bound_floor() -> None:
    ctx = ReduceContext(temporal=TemporalContext.empty())
    ctx = bind_temporal(
        ctx,
        "n",
        TermValue(10),
        owner="test seed",
        blame="t.py:1:0",
    )

    rewritten = rewrite_temporal(
        ctx,
        AddAssignRewriteOperation(
            name="n",
            value=TermValue(1),
            owner="test rewrite",
            blame="t.py:2:0",
        ),
        owner="test rewrite",
        blame="t.py:2:0",
    )

    assert rewritten.temporal.value_for("n") == TermValue(11)
    assert ctx.operation_log == [
        ("test seed", "bind_with", "BindValueOperation"),
        ("test rewrite", "rewrite_with", "AddAssignRewriteOperation"),
        ("test rewrite", "add_with", "AddOperation"),
    ]


def test_temporal_dispatch_gap_names_missing_operation() -> None:
    ctx = ReduceContext(temporal=TemporalContext.empty())

    with pytest.raises(FactoryGap) as gap:
        perform_temporal_operation(
            owner="test gap",
            blame="t.py:1:0",
            receiver=ctx.temporal,
            method_name="unknown_with",
            operation=object(),
            ctx=ctx,
        )

    assert gap.value.info == {
        "owner": "test gap",
        "blame": "t.py:1:0",
        "observed": "TemporalContext",
        "requested": "unknown_with",
            "fix": (
                "add unknown_with to TemporalContext or route this curry/rewrite "
                "through the temporal floor"
            ),
            "gap_kind": "Floor",
            "gap_locus": "construction",
        }


def test_rewrite_temporal_add_assign_bad_operand_names_floor_gap() -> None:
    ctx = ReduceContext(temporal=TemporalContext.empty())
    ctx = bind_temporal(
        ctx,
        "n",
        TermValue(10),
        owner="test seed",
        blame="t.py:1:0",
    )

    with pytest.raises(FactoryGap) as gap:
        rewrite_temporal(
            ctx,
            AddAssignRewriteOperation(
                name="n",
                value=ArrayLiteral((TermValue(1),)),
                owner="test rewrite",
                blame="t.py:2:0",
            ),
            owner="test rewrite",
            blame="t.py:2:0",
        )

    assert gap.value.info == {
        "owner": "test rewrite",
        "blame": "t.py:2:0",
        "observed": "TermValue+ArrayLiteral",
        "requested": "add operand floor",
        "fix": "add AddOperation support for TermValue with ArrayLiteral",
        "gap_kind": "Floor",
        "gap_locus": "construction",
    }
