from __future__ import annotations

import pytest

from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import euf_call_term
from sugar_lift_py_tests.floor import (
    BlockValue,
    BoolValue,
    Bv32Value,
    CallSiteValue,
    ObjectValue,
    ReturnValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import bool_const, eq, make_var, num, str_const
from sugar_lift_py_tests.operations import (
    CallsiteProjectionOperation,
    perform_operation,
)


def _operation() -> CallsiteProjectionOperation:
    return CallsiteProjectionOperation(
        callee_name="callee",
        arg_terms=(num(5),),
        owner="CallsiteProjectionTest",
        blame="t.py:1",
    )


def _project(receiver, ctx: ReduceContext | None = None):
    ctx = ctx or ReduceContext.root(owner="projection-test")
    return perform_operation(
        owner="CallsiteProjectionTest",
        blame="t.py:1",
        receiver=receiver,
        method_name="project_callsite_with",
        operation=_operation(),
        ctx=ctx,
    )


def _call_term():
    return euf_call_term("callee", [num(5)])


@pytest.mark.parametrize(
    ("receiver", "expected"),
    [
        (TermValue(0), num(0)),
        (BoolValue(True), bool_const(True)),
        (StringValue("ok"), str_const("ok")),
        (Bv32Value(make_var("byte_x_0")), make_var("byte_x_0")),
    ],
)
def test_literal_floor_values_project_exact_callsite_fact_by_dispatch(
    receiver, expected
) -> None:
    ctx = ReduceContext.root(owner="projection-test")

    fact = _project(receiver, ctx)

    assert fact == eq(_call_term(), expected)
    assert ctx.operation_log == [
        (
            "CallsiteProjectionTest",
            "project_callsite_with",
            "CallsiteProjectionOperation",
        )
    ]


def test_callsite_value_projects_bridge_term_without_reenqueue() -> None:
    sink = [("already", TermValue(1))]
    ctx = ReduceContext.root(owner="projection-test", dig_sink=sink)
    bridge_term = euf_call_term("inner", [num(2)])
    receiver = CallSiteValue(
        target_name="inner",
        arg_values=(TermValue(2),),
        parameters=("x",),
        term=bridge_term,
        body=None,
    )

    fact = _project(receiver, ctx)

    assert fact == eq(_call_term(), bridge_term)
    assert sink == [("already", TermValue(1))]


def test_symbolic_value_projects_no_floor_fact() -> None:
    fact = _project(SymbolicValue(make_var("x")))

    assert fact is None


def test_return_value_and_single_exit_block_reproject_transparently() -> None:
    expected = eq(_call_term(), num(7))

    assert _project(ReturnValue(TermValue(7))) == expected
    assert _project(BlockValue((ReturnValue(TermValue(7)),))) == expected


def test_multi_exit_block_projects_no_single_floor_fact() -> None:
    fact = _project(
        BlockValue(
            (
                ReturnValue(TermValue(1)),
                ReturnValue(TermValue(2)),
            )
        )
    )

    assert fact is None


def test_unprojectable_floor_refuses_with_projection_gap() -> None:
    receiver = ObjectValue(class_name="Box", fields=(), identity="box-1")

    with pytest.raises(FactoryGap) as exc:
        _project(receiver)

    assert exc.value.info["gap_kind"] == "Floor"
    assert exc.value.info["gap_locus"] == "Projection"
    assert exc.value.info["observed"] == "ObjectValue"
    assert exc.value.info["requested"] == "project callsite floor"
