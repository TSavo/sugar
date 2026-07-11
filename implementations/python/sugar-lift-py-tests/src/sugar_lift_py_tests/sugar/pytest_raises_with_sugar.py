from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


def _is_raises_context(site) -> bool:
    """True when the with-item context expression is pytest.raises / raises(...)."""
    if site.observed != "Call":
        return False
    # pytest.raises(...) — Attribute receiver pytest, method raises
    if site.call_receiver() is not None:
        name = site.call_target_name()
        if name != "raises":
            return False
        recv = site.call_receiver()
        if recv.observed == "Name" and recv.name_id() == "pytest":
            return True
        if recv.observed == "Attribute" and recv.attr_name() == "raises":
            return True
        # bare attr chain ending in raises already handled by target_name
        return name == "raises"
    # bare raises(...) if imported as from pytest import raises
    return site.call_target_name() == "raises"


def _raises_exception_type_name(site) -> str | None:
    """First positional arg of raises(Type) or raises(Type, ...)."""
    if site.observed != "Call":
        return None
    args = list(site.call_args())
    if not args:
        # keyword only: expected_exception=...
        for kw in site.call_keywords():
            if kw.keyword_arg_name() in {"expected_exception", "exception"}:
                return _type_name(kw.keyword_value())
        return None
    return _type_name(args[0])


def _type_name(site) -> str | None:
    if site.observed == "Name":
        return site.name_id()
    if site.observed == "Attribute":
        recv = _type_name(site.attr_receiver())
        if recv:
            return f"{recv}.{site.attr_name()}"
        return site.attr_name()
    if site.observed == "Call":
        return site.call_target_name()
    return None


@dataclass(frozen=True)
class PytestRaisesWithSugar(
    Sugar, role=SugarRole.STATEMENT, comes_before=("WithSugar",)
):
    """`with pytest.raises(T) [as exc_info]: body` — testimony of an expected raise.

    Doctrine (option A): state an inv ``pytest.raises(T)`` when the with-context
    is recognizably raises(T). Body reduces under optional ``as`` binding
    (``python:exc_info``). Does **not** invent that the body raised at runtime;
    the inv is the **test's stated contract** (the CM request), same class as
    an assert's inv — Stated from the with locus.

    Single-item With only (same as WithSugar). Multi-item stays unowned.
    """

    exception_type_name: str | None
    as_name: str | None
    body: SugarBody
    context: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "With":
            return False
        if site.with_item_count() != 1:
            return False
        observed = site.with_optional_vars_observed()
        if observed is not None and site.with_optional_vars_name() is None:
            return False
        return _is_raises_context(site.with_context_expr(0))

    @classmethod
    def new(cls, site, ctx) -> "PytestRaisesWithSugar":
        ctx_expr = site.with_context_expr(0)
        return cls(
            exception_type_name=_raises_exception_type_name(ctx_expr),
            as_name=site.with_optional_vars_name(0),
            body=ctx.build_body(site.with_body(), SugarRole.STATEMENT),
            context=ctx.build_body(ctx_expr, SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "import pytest\n"
            "def boom():\n"
            "    raise ValueError(\"x\")\n"
            "def A(z):\n"
            "    with pytest.raises(ValueError):\n"
            "        boom()\n"
            "    return 1\n"
            "\n"
        )
        return _call_pair(
            name="pytest_raises_with_return",
            owner_sugar="PytestRaisesWithSugar",
            truthful=prefix + "def test_a():\n    assert A(1) == 1\n",
            lying=prefix + "def test_a():\n    assert A(1) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor import (
            InvValue,
            RaisesWithValue,
            ScopeRebind,
            SymbolicValue,
        )
        from sugar_lift_py_tests.ir import ctor, py_raises, str_const

        exc_info = SymbolicValue(ctor("python:exc_info", []))
        body_ctx = ctx
        if self.as_name is not None:
            # Inside the with body, exc_info is already bound (pytest semantics).
            body_ctx = ScopeRebind(self.as_name, exc_info).extend_scope(ctx)

        type_term = ctor(
            "python:type",
            [str_const(self.exception_type_name or "Exception")],
        )
        raises_inv = InvValue(py_raises(type_term), self.site)

        def _splice(body_val):
            if hasattr(body_val, "contribution"):
                rest = body_val.contribution()
            else:
                rest = (body_val,)
            return Complete(
                RaisesWithValue(
                    raises_inv=raises_inv,
                    body_entries=rest,
                    as_name=self.as_name,
                    as_value=exc_info if self.as_name is not None else None,
                )
            )

        return self.body.reduce(body_ctx).and_then(_splice)

    def walk_children(self):
        return (self.context, self.body)
