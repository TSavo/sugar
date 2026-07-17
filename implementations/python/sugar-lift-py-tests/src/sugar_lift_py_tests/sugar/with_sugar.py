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
            # A source-backed producer may expose its complete manager result.
            # Dig that result structurally so __enter__/__exit__ resolve on the
            # exact ObjectValue method table; never borrow a same-leaf method
            # from a resolver or invent a suppression contract.
            manager = cm._dig_floor_or_none(ctx, owner="WithSugar manager result")
            if isinstance(manager, ObjectValue):
                enter_call = manager.call_method_value(
                    "__enter__",
                    (),
                    owner=type(self).__name__,
                    blame=str(self.site),
                    ctx=ctx,
                ).value
                entered = force_floor(
                    enter_call, ctx, owner="WithSugar.__enter__", project_callsite=False
                )
            else:
                # Coordinate-only managers keep the historical non-raising
                # rewrite. A raising body below turns this soft coordinate into
                # a hard demand for the exact manager result and __exit__ body.
                entered = cm.linear_method_call("__enter__", (), self.site)

            body_ctx = ctx
            if as_name is not None:
                body_ctx = ScopeRebind(as_name, entered).extend_scope(ctx)
            outcome = self._enter_items(remaining, body_ctx)
            if not _carries_raise_effect(outcome):
                return outcome

            if cm.exit_suppression is not None:
                if not cm.exit_suppression.exception_names:
                    return outcome
                exception_names = _raised_exception_names(outcome)
                if exception_names is None:
                    _unresolved_callsite_exit(self.site)
                if exception_names and all(
                    cm.exit_suppression.suppresses_exception(name)
                    for name in exception_names
                ):
                    from sugar_lift_py_tests.floor import BlockValue
                    from sugar_lift_py_tests.outcome import Complete

                    if as_name is not None:
                        return Complete(ScopeRebind(as_name, entered))
                    return Complete(BlockValue(()))
                return outcome

            if not isinstance(manager, ObjectValue):
                if cm.body is None:
                    _unresolved_callsite_exit(self.site)
                manager = force_floor(
                    cm, ctx, owner="WithSugar manager result", project_callsite=False
                )
            if not isinstance(manager, ObjectValue) or not manager.has_method(
                "__exit__"
            ):
                _unresolved_callsite_exit(self.site)

            exit_call = manager.call_method_value(
                "__exit__",
                (entered, entered, entered),
                owner=type(self).__name__,
                blame=str(self.site),
                ctx=ctx,
            ).value
            exit_value = force_floor(
                exit_call, ctx, owner="WithSugar.__exit__", project_callsite=False
            )
            if _constructed_truthy(exit_value, self.site):
                from sugar_lift_py_tests.floor import BlockValue
                from sugar_lift_py_tests.outcome import Complete

                # Suppression removes the exceptional body contribution and
                # permits the enclosing block to continue after the with. The
                # optional-as binding remains live after the with statement.
                if as_name is not None:
                    return Complete(ScopeRebind(as_name, entered))
                return Complete(BlockValue(()))
            return outcome

        if not isinstance(cm, ObjectValue):
            return cm._floor_gap(
                owner=type(self).__name__,
                blame=str(self.site),
                observed=type(cm).__name__,
                requested="context manager data-model methods",
                fix="construct __enter__ and __exit__",
            )

        class ContextManagerOperation:
            pass

        ctx.record_operation(
            owner="WithSugar",
            method_name="context_manager_with",
            operation=ContextManagerOperation(),
        )
        enter = cm.call_method_value(
            "__enter__", (), owner=type(self).__name__, blame=str(self.site), ctx=ctx
        ).value
        entered = force_floor(enter, ctx, owner="WithSugar.__enter__")
        body_ctx = ctx
        if as_name is not None:

            class BindValueOperation:
                pass

            ctx.record_operation(
                owner="WithSugar",
                method_name="bind_with",
                operation=BindValueOperation(),
            )
            body_ctx = ScopeRebind(as_name, entered).extend_scope(ctx)
        outcome = self._enter_items(remaining, body_ctx)
        exit_call = cm.call_method_value(
            "__exit__",
            (entered, entered, entered),
            owner=type(self).__name__,
            blame=str(self.site),
            ctx=ctx,
        ).value
        exit_value = force_floor(
            exit_call, ctx, owner="WithSugar.__exit__", project_callsite=False
        )
        if isinstance(exit_value, TermValue) and bool(exit_value.value):
            force_floor(exit_call, ctx, owner="WithSugar.__exit__")
        return outcome

    def walk_children(self):
        return (*(context for context, _as_name in self.items), self.body)


def _unresolved_callsite_exit(site) -> None:
    from sugar_lift_py_tests.factory import factory_panic_gap

    factory_panic_gap(
        owner="WithSugar",
        blame=str(site),
        observed="raise-carrying callsite with-body",
        requested="dig manager().__exit__ exception suppression contract",
        fix="attach the exact __exit__ method body before reducing a raising with-body",
    )


def _constructed_truthy(value, site) -> bool:
    """Suppress only when the constructed __exit__ result folds to literal True."""
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    truth = value.truth(site)
    if isinstance(truth, Incomplete):
        return False
    return type(getattr(truth, "value", None)) is TrueBoolLiteralSugar


def _carries_raise_effect(outcome) -> bool:
    from sugar_lift_py_tests.floor import (
        BlockValue,
        GuardedRaise,
        RaiseValue,
        RaisesWithValue,
    )
    from sugar_lift_py_tests.outcome import Incomplete

    if isinstance(outcome, Incomplete):
        return True
    value = getattr(outcome, "value", None)
    if not isinstance(value, BlockValue):
        return False
    return any(
        isinstance(entry, (Incomplete, GuardedRaise, RaiseValue, RaisesWithValue))
        for entry in value.statements
    )


def _raised_exception_names(outcome) -> tuple[str, ...] | None:
    """Return every statically named raise carried by a completed block."""
    from sugar_lift_py_tests.floor import BlockValue, RaiseValue
    from sugar_lift_py_tests.outcome import Incomplete

    if isinstance(outcome, Incomplete):
        return None
    value = getattr(outcome, "value", None)
    if not isinstance(value, BlockValue):
        return ()
    names: list[str] = []
    for entry in value.statements:
        if isinstance(entry, RaiseValue) and entry.effect.exception_name is not None:
            names.append(entry.effect.exception_name)
        elif _entry_carries_raise(entry):
            return None
    return tuple(names)


def _entry_carries_raise(entry) -> bool:
    from sugar_lift_py_tests.floor import GuardedRaise, RaisesWithValue
    from sugar_lift_py_tests.outcome import Incomplete

    return isinstance(entry, (Incomplete, GuardedRaise, RaisesWithValue))
