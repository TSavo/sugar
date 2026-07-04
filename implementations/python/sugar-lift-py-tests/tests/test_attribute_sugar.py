"""AttributeSugar lowers Python attribute access to the `py.attr` ctor."""

from __future__ import annotations

import ast

import pytest

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.ir import ctor, make_var, str_const
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar


def _audit_row(info: FactoryGapInfo) -> FactoryAuditRow:
    return FactoryAuditRow(
        role="test",
        status="floor-gap",
        observed=info.observed,
        blame=info.blame,
        selected=None,
        candidates=[],
        message=info.message,
    )


class _GapBody:
    def reduce(self, ctx):
        info = FactoryGapInfo(
            owner="test",
            blame="t.py:1",
            observed="Call",
            requested="reduce a receiver",
            fix="write more Floor",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.REDUCE,
        )
        raise FactoryGap(info, _audit_row(info))


class _TypeErrorBody:
    def reduce(self, ctx):
        raise TypeError("reduce bug, not a recognition miss")


def _reduce_outcome(expr: str):
    ctx = FactoryBuildContext(filename="attribute.py", catalog=default_catalog())
    body = ctx.build_body(ast.parse(expr, mode="eval").body, SugarRole.TERM)
    return body.reduce(ReduceContext.root(owner="attribute-test"))


def test_attribute_reduces_to_py_attr_ctor() -> None:
    assert fol(reduce_term("arr.shape")) == fol(
        ctor("py.attr", [make_var("arr"), str_const("shape")])
    )


def test_call_result_attribute_reduces_to_py_attr_ctor() -> None:
    assert fol(reduce_term("np.any(arr).dtype")) == fol(
        ctor(
            "py.attr",
            [
                ctor("call:any", [make_var("np"), make_var("arr")]),
                str_const("dtype"),
            ],
        )
    )


def test_dynamic_subscript_attribute_receiver_refuses() -> None:
    outcome = _reduce_outcome("d[...].flags.writeable")

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "attribute lookup runtime boundary" in outcome.reason
    assert (
        "attribute receiver `Attribute` requires runtime evaluation" in outcome.reason
    )
    assert "typed red" in outcome.reason
    assert "blame=" in outcome.reason


def test_dynamic_call_attribute_receiver_refuses() -> None:
    outcome = _reduce_outcome("np.add(1, 2, **get_kwarg(int64_2)).dtype")

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "attribute lookup runtime boundary" in outcome.reason
    assert "attribute receiver `Call` requires runtime evaluation" in outcome.reason
    assert "typed red" in outcome.reason
    assert "blame=" in outcome.reason


def test_desugar_propagates_floor_gaps() -> None:
    sugar = AttributeSugar(
        term=str_const("t"),
        receiver=_GapBody(),
        receiver_name=None,
        name="x",
        blame="t.py:1",
    )
    with pytest.raises(FactoryGap):
        sugar.desugar(ctx=None)


def test_desugar_propagates_type_errors() -> None:
    sugar = AttributeSugar(
        term=str_const("t"),
        receiver=_TypeErrorBody(),
        receiver_name=None,
        name="x",
        blame="t.py:1",
    )
    with pytest.raises(TypeError):
        sugar.desugar(ctx=None)
