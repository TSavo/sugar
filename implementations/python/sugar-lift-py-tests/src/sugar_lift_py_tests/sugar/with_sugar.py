from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class WithSugar(Sugar, role=SugarRole.STATEMENT):
    """`with cm as y: body` -- substitute the manager coordinate into the body.

    Single-item synchronous With only. Multi-item `with a, b:` and
    AsyncWith stay unowned (loud factory gap) -- this arm does not take
    the first item and drop the rest. Complex `as` targets (tuple, attr)
    are also unowned.

    Reduce the context expression; the entered value is the unary
    coordinate call:__enter__(cm), same head family as method calls.
    Bind optional `as y` via ScopeRebind, then reduce the body under
    that scope. The With is a scope+sequence construct: its outcome is
    the body's BlockValue, which splices into the enclosing record.
    """

    items: tuple[tuple[SugarBody, str | None], ...]
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "With":
            return False
        return all(
            site.with_optional_vars_observed(index) is None
            or site.with_optional_vars_name(index) is not None
            for index in range(site.with_item_count())
        )

    @classmethod
    def new(cls, site, ctx) -> "WithSugar":
        # Context expr (TERM), optional as-name, body block (STATEMENT).
        # Never reduce here.
        return cls(
            items=tuple(
                (
                    ctx.build_body(site.with_context_expr(index), SugarRole.TERM),
                    site.with_optional_vars_name(index),
                )
                for index in range(site.with_item_count())
            ),
            body=ctx.build_body(site.with_body(), SugarRole.STATEMENT),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Coordinate rides inside the with-body; the pair discriminates on
        # the enclosing return face (no concrete CM fold yet).
        prefix = (
            "def A(z):\n"
            "    with z.lock() as g:\n"
            "        return 1\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="with_return",
            owner_sugar="WithSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce the context; enter-coordinate + body under optional as-binding.
        return self._enter_items(self.items, ctx)

    def _enter_items(self, remaining, ctx) -> Outcome:
        if not remaining:
            return self.body.reduce(ctx)
        (context, as_name), *rest = remaining
        return context.reduce(ctx).and_then(
            lambda cm: self._enter_one(cm, as_name, tuple(rest), ctx)
        )

    def _enter_one(self, cm, as_name, remaining, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import (
            CallSiteValue,
            ObjectValue,
            ScopeRebind,
            TermValue,
        )
        from sugar_lift_py_tests.floor.call_site_value import force_floor

        if isinstance(cm, CallSiteValue):
            # Timeless substitution: ``with manager() as value`` is the body
            # with the frozen manager call coordinate written for ``value``.
            # Enter/exit events are ghosts of motion. If the callable has a
            # contract, ordinary downstream floors may dig it from this same
            # coordinate; WithSugar does not execute a protocol side door.
            body_ctx = ctx
            if as_name is not None:
                body_ctx = ScopeRebind(as_name, cm).extend_scope(ctx)
            return self._enter_items(remaining, body_ctx)

        if not isinstance(cm, ObjectValue):
            return cm._floor_gap(owner=type(self).__name__, blame=str(self.site), observed=type(cm).__name__, requested="context manager data-model methods", fix="construct __enter__ and __exit__")
        class ContextManagerOperation: pass
        ctx.record_operation(owner="WithSugar", method_name="context_manager_with", operation=ContextManagerOperation())
        enter = cm.call_method_value("__enter__", (), owner=type(self).__name__, blame=str(self.site), ctx=ctx).value
        entered = force_floor(enter, ctx, owner="WithSugar.__enter__")
        body_ctx = ctx
        if as_name is not None:
            class BindValueOperation: pass
            ctx.record_operation(owner="WithSugar", method_name="bind_with", operation=BindValueOperation())
            body_ctx = ScopeRebind(as_name, entered).extend_scope(ctx)
        outcome = self._enter_items(remaining, body_ctx)
        exit_call = cm.call_method_value("__exit__", (entered, entered, entered), owner=type(self).__name__, blame=str(self.site), ctx=ctx).value
        exit_value = force_floor(exit_call, ctx, owner="WithSugar.__exit__", project_callsite=False)
        if isinstance(exit_value, TermValue) and bool(exit_value.value):
            force_floor(exit_call, ctx, owner="WithSugar.__exit__")
        return outcome

    def walk_children(self):
        return (*(context for context, _as_name in self.items), self.body)
