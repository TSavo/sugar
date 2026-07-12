from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TryExceptArm:
    """One `except Type [as name]: body` arm (Type may be multi-name)."""

    type_names: tuple[str, ...]
    type_body: SugarBody
    as_name: str | None
    body: SugarBody

    @property
    def type_name(self) -> str:
        # Primary name for single-type; joined for multi (display / py.except).
        return self.type_names[0] if len(self.type_names) == 1 else ",".join(self.type_names)


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
      * each handler has one or more simple exception type names (Name/Attribute)
      * multi-type `except (A, B):` owned (names joined in py.except coordinate)
      * no bare `except:`
      * no finally: clause
      * one narrow else shape: try assignment, one typed raise handler, return

    LOUD gaps (not owned -- FactoryPanic):
      * bare except, broad else, finally, TryStar, zero handlers,
        empty/unresolvable types

    Does NOT model exception control-flow execution -- recognition + threading
    only. Never silently drops a body, handler, else, or finally.
    """

    body: SugarBody
    handlers: tuple[TryExceptArm, ...]
    else_body: SugarBody | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Try":
            return False
        if site.try_finalbody() is not None:
            return False
        handlers = site.try_handlers()
        if not handlers:
            return False
        for handler in handlers:
            names = handler.except_handler_type_names()
            # Bare except -> None; empty / unresolvable types refuse loud.
            if names is None or len(names) < 1:
                return False
        orelse = site.try_orelse()
        if orelse is not None:
            # Exception-flow joins are deliberately narrow: the vendor-common
            # lookup fallback has one assignment in the try face, one typed
            # handler, and one return in the no-exception face. Broader try
            # semantics remain the loud None arm.
            if len(handlers) != 1:
                return False
            if tuple(stmt.observed for stmt in site.try_body().statements()) != (
                "Assign",
            ):
                return False
            handler_shapes = tuple(
                stmt.observed
                for stmt in handlers[0].except_handler_body().statements()
            )
            if handler_shapes != ("Raise",):
                return False
            if tuple(stmt.observed for stmt in orelse.statements()) != ("Return",):
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
                    type_names=tuple(names),
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
            else_body=(
                ctx.build_body(site.try_orelse(), SugarRole.STATEMENT)
                if site.try_orelse() is not None
                else None
            ),
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
        if self.else_body is not None:
            return self._desugar_else(ctx)
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
            term=ctor(
                "py.except",
                [str_const(n) for n in arm.type_names],
            ),
            body=None,
            site=self.site,
        )
        body_ctx = ctx
        if arm.as_name is not None:
            body_ctx = ScopeRebind(arm.as_name, catch).extend_scope(ctx)

        return arm.body.reduce(body_ctx).and_then(
            lambda hblock: self._collect_handlers(
                (
                    *accumulated,
                    *_except_arm_contributions(hblock.contribution(), arm),
                ),
                index + 1,
                ctx,
            )
        )

    def _desugar_else(self, ctx: object) -> Outcome:
        """Reduce the narrow lookup fallback without choosing an exception face."""
        from sugar_lift_py_tests.floor import BlockValue
        from sugar_lift_py_tests.ir import ctor, not_, str_const
        from sugar_lift_py_tests.outcome import complete_value

        arm = self.handlers[0]
        exception_guard = ctor(
            "py.except", [str_const(name) for name in arm.type_names]
        )
        body_scope = self.body.sugar.scope_after(ctx)
        handler_value = complete_value(
            arm.body.reduce(ctx), owner="try except handler"
        )
        else_value = complete_value(
            self.else_body.reduce(body_scope), owner="try else body"
        )
        entries = (
            *tuple(
                entry.guarded(exception_guard)
                for entry in handler_value.contribution()
            ),
            *tuple(
                entry.guarded(not_(exception_guard))
                for entry in else_value.contribution()
            ),
        )
        return Complete(BlockValue(entries))

    def walk_children(self):
        children: list[SugarBody] = [self.body]
        for arm in self.handlers:
            children.append(arm.type_body)
            children.append(arm.body)
        if self.else_body is not None:
            children.append(self.else_body)
        return tuple(children)


def _except_arm_contributions(entries: tuple, arm: "TryExceptArm") -> tuple:
    """Except-arm returns must not unguard-kill the rest of the outer block.

    Recognition threading splices handler bodies into the enclosing record. An
    unguarded ReturnValue.follow_rest keeps the tail raw — which would drop
    asserts *after* a try/except that only returns on the exception path.
    Wrap handler returns as GuardedReturn under py.except(type) so the tail
    still reduces.
    """
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.ir import ctor, str_const

    guard = ctor("py.except", [str_const(n) for n in arm.type_names])
    out = []
    for entry in entries:
        if type(entry) is ReturnValue:
            out.append(GuardedReturn(guards=(guard,), value=entry.value))
        else:
            out.append(entry)
    return tuple(out)
