from __future__ import annotations

from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import SourceFragment
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ObjectMethodValue,
    ObjectValue,
    StringValue,
)
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.temporal import TemporalContext


def _expr_site(expr: str) -> SourceFragment:
    suite = SourceFragment.from_source(expr, "t.py").statements()[0]
    return suite.statements()[0].expr_value()


def _body_for_expr(expr: str):
    ctx = FactoryBuildContext(filename="method.py", catalog=default_catalog())
    return ctx.build_body(_expr_site(expr), SugarRole.TERM)


def _repr_object() -> ObjectValue:
    return ObjectValue(
        class_name="Box",
        fields=(),
        methods=(
            ObjectMethodValue(
                name="__repr__",
                parameters=("self",),
                body=_body_for_expr("'Box<1>'"),
            ),
        ),
        identity="fixture",
    )


def _reduce_expr(expr: str):
    temporal = TemporalContext.empty().bind_value("obj", _repr_object())
    ctx = FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        temporal=temporal,
    )
    value = complete_value(
        ctx.build_body(_expr_site(expr), SugarRole.TERM).reduce(ctx),
        owner="repr dunder bridge",
    )
    return value, ctx


def test_repr_builtin_projects_object_to_dunder_method_bridge() -> None:
    value, _ctx = _reduce_expr("repr(obj)")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__repr__"
    assert fol(floor_to_term(value, owner="repr dunder bridge")) == fol(
        ctor(
            "call:Box.__repr__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Box"), str_const("fixture")],
                )
            ],
        )
    )


def test_repr_builtin_dunder_can_be_forced_to_string_value() -> None:
    value, ctx = _reduce_expr("repr(obj)")

    assert force_floor(value, ctx, owner="repr dunder bridge") == StringValue("Box<1>")
