"""AttributeSugar lowers Python attribute access to the call:<attr> coordinate."""

from __future__ import annotations

import ast

import pytest

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import ArrayLiteral
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


def test_attribute_reduces_to_call_attr_coordinate() -> None:
    assert fol(reduce_term("arr.shape")) == fol(
        ctor("call:shape", [make_var("arr")])
    )


def test_call_result_attribute_reduces_to_call_attr_coordinate() -> None:
    assert fol(reduce_term("np.any(arr).dtype")) == fol(
        ctor(
            "call:dtype",
            [ctor("call:any", [make_var("np"), make_var("arr")])],
        )
    )


def test_dynamic_subscript_attribute_receiver_is_typed_runtime_effect() -> None:
    ctx = FactoryBuildContext(filename="attribute.py", catalog=default_catalog())
    body = ctx.build_body(
        ast.parse("d[...].flags.writeable", mode="eval").body,
        SugarRole.TERM,
    )

    outcome = body.reduce(ReduceContext.root(owner="attribute-test"))

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "attribute lookup runtime boundary" in outcome.effect.reason
    assert "attribute receiver `Attribute` requires runtime evaluation" in (
        outcome.effect.reason
    )
    assert "typed red" in outcome.effect.reason
    assert "blame=" in outcome.effect.reason


def test_dynamic_call_attribute_receiver_is_typed_runtime_effect() -> None:
    ctx = FactoryBuildContext(filename="attribute.py", catalog=default_catalog())
    body = ctx.build_body(
        ast.parse("np.add(1, 2, **get_kwarg(int64_2)).dtype", mode="eval").body,
        SugarRole.TERM,
    )

    outcome = body.reduce(ReduceContext.root(owner="attribute-test"))

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "attribute lookup runtime boundary" in outcome.effect.reason
    assert "attribute receiver `Call` requires runtime evaluation" in (
        outcome.effect.reason
    )
    assert "typed red" in outcome.effect.reason
    assert "blame=" in outcome.effect.reason


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


def test_list_bound_attribute_missing_floor_is_typed_runtime_boundary() -> None:
    node = ast.parse("items.append", mode="eval").body
    build_ctx = FactoryBuildContext(filename="attr.py", catalog=default_catalog())
    temporal = build_ctx.temporal.bind_value("items", ArrayLiteral(()))
    body = build_ctx.with_temporal(temporal).build_body(node, SugarRole.TERM)
    outcome = body.reduce(ReduceContext(temporal=temporal))

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "RuntimeEffect"
    assert "attribute access runtime boundary" in outcome.reason
    assert "ArrayLiteral.append" in outcome.reason


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
