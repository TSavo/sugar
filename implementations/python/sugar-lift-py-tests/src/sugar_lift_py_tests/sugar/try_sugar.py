from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TryExceptArm:
    """One `except Type [as name]: body` arm."""

    type_name: str
    type_body: SugarBody
    as_name: str | None
    body: SugarBody


@dataclass(frozen=True)
class TrySugar(Sugar, role=SugarRole.STATEMENT):
    """`try: body except Type [as name]: handler ...` -- recognition + threading.

    Threads the try body and each except-handler body into the enclosing
    record. Each handler carries its caught type as a py.except coordinate
    (not dropped). Optional `as name` binds that coordinate via ScopeRebind
    for the handler body only.

    OWNED shapes (this arm):
      * observed == "Try"
      * one or more except handlers
      * each handler has exactly one simple exception type name (Name/Attribute)
      * no bare `except:`
      * no multi-type `except (A, B):`
      * no else: clause
      * no finally: clause

    LOUD gaps (not owned -- FactoryPanic):
      * bare except, tuple except types, else, finally, TryStar, zero handlers

    Does NOT model exception control-flow execution -- recognition + threading
    only. Never silently drops a body, handler, else, or finally.
    """

    body: SugarBody
    handlers: tuple[TryExceptArm, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Try":
            return False
        # else / finally not threaded this arm -- require absent.
        if site.try_orelse() is not None:
            return False
        if site.try_finalbody() is not None:
            return False
        handlers = site.try_handlers()
        if not handlers:
            return False
        for handler in handlers:
            names = handler.except_handler_type_names()
            # Bare except -> None; unowned multi-type or empty tuple -> not exactly one.
            if names is None or len(names) != 1:
                return False
        return True

    @classmethod
    def new(cls, site, ctx) -> "TrySugar":
        # Body + each handler type (TERM) and body (STATEMENT). Never reduce here.
        arms: list[TryExceptArm] = []
        for handler in site.try_handlers():
            names = handler.except_handler_type_names()
            type_frag = handler.except_handler_type()
            arms.append(
                TryExceptArm(
                    type_name=names[0],
                    type_body=ctx.build_body(type_frag, SugarRole.TERM),
                    as_name=handler.except_handler_name(),
                    body=ctx.build_body(
                        handler.except_handler_body(), SugarRole.STATEMENT
                    ),
                )
            )
        return cls(
            body=ctx.build_body(site.try_body(), SugarRole.STATEMENT),
            handlers=tuple(arms),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Try-body return face: truthful rides 1, lying asserts 0.
        prefix = (
            "def A(z):\n"
            "    try:\n"
            "        return 1\n"
            "    except ValueError:\n"
            "        return 0\n"
            "\n"
        )
        return _call_pair(
            name="try_return",
            owner_sugar="TrySugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Thread try body, then each guarded handler into one spliced BlockValue.
        return self.body.reduce(ctx).and_then(
            lambda body_val: self._collect_handlers(
                tuple(body_val.contribution()), 0, ctx
            )
        )

    def _collect_handlers(
        self, accumulated: tuple, index: int, ctx: object
    ) -> Outcome:
        from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, ScopeRebind
        from sugar_lift_py_tests.ir import ctor, str_const

        if index >= len(self.handlers):
            return Complete(BlockValue(accumulated))

        arm = self.handlers[index]
        # Caught type rides as a recognition coordinate -- not dropped.
        catch = CallSiteValue(
            target_name="except",
            arg_values=(),
            parameters=(),
            term=ctor("py.except", [str_const(arm.type_name)]),
            body=None,
            site=self.site,
        )
        body_ctx = ctx
        if arm.as_name is not None:
            body_ctx = ScopeRebind(arm.as_name, catch).extend_scope(ctx)

        return arm.body.reduce(body_ctx).and_then(
            lambda hblock: self._collect_handlers(
                (*accumulated, *hblock.contribution()),
                index + 1,
                ctx,
            )
        )

    def walk_children(self):
        children: list[SugarBody] = [self.body]
        for arm in self.handlers:
            children.append(arm.type_body)
            children.append(arm.body)
        return tuple(children)
