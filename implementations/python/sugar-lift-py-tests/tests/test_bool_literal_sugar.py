"""True and False are two distinct literal sugars. Each is its own floor value and
its own dispatcher on the bool floor: True returns the then, False the else. No fork,
no field, no standing in between."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import BlockValue, ScopeRebind, StringValue
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def _build(source: str, ctx: FactoryBuildContext):
    node = ast.parse(source, mode="eval").body
    return build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar


def test_factory_builds_true_and_false_literals() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())

    assert isinstance(_build("True", ctx), TrueBoolLiteralSugar)
    assert isinstance(_build("False", ctx), FalseBoolLiteralSugar)


class _Branch:
    def __init__(self, tag: str) -> None:
        self.tag = tag

    def reduce(self, ctx: object = None) -> str:
        return self.tag


def test_bool_floor_dispatches_through_the_literal() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    then, else_ = _Branch("then"), _Branch("else")

    true_lit = _build("True", ctx)
    false_lit = _build("False", ctx)

    # the literal IS the dispatcher: no fork at the call site.
    assert true_lit.desugar(ctx).binary_conditional(then, else_, ctx) == "then"
    assert false_lit.desugar(ctx).binary_conditional(then, else_, ctx) == "else"


class _ScopedBranch:
    sugar = None

    def __init__(self) -> None:
        self.sugar = self

    def reduce_with_scope(self, ctx):
        from sugar_lift_py_tests.outcome import Complete

        final_ctx = ctx.with_temporal(
            ctx.temporal.bind_value("dtype", StringValue("m8[ns]"))
        )
        return Complete(BlockValue(())), final_ctx


def test_false_face_carries_selected_else_scope_rebind() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    false_lit = _build("False", ctx)

    outcome = false_lit.binary_conditional(_Branch("then"), _ScopedBranch(), ctx)

    assert outcome.value.statements == (
        ScopeRebind("dtype", StringValue("m8[ns]")),
    )
