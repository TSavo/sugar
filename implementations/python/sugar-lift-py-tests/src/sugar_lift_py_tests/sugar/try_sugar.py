from __future__ import annotations

import ast
from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TryExceptArm:
    """One `except Type [as name]: body` arm (Type may be multi-name)."""

    type_names: tuple[str, ...] | None
    type_body: SugarBody | None
    as_name: str | None
    body: SugarBody

    @property
    def type_name(self) -> str:
        # Primary name for single-type; joined for multi (display / py.except).
        return (
            "<runtime>"
            if self.type_names is None
            else self.type_names[0]
            if len(self.type_names) == 1
            else ",".join(self.type_names)
        )


@dataclass(frozen=True)
class TrySugar(Sugar, role=SugarRole.STATEMENT):
    """`try: body except Type [as name]: handler ...` -- recognition + threading.

    Threads the try body and each except-handler body into the enclosing
    record. Each handler carries its caught type as a py.except coordinate
    (not dropped). Optional `as name` binds that coordinate via ScopeRebind
    for the handler body only.

    Named, tuple, and bare handlers carry source-cited ``py.except`` guards.
    Runtime-computed handler expressions become a named typed effect. Else
    entries ride under the negated handler union. Non-terminal finally bodies
    sequence unconditionally; a finally return/raise/break/continue remains a
    loud parent gap because it overrides the preceding control-flow result.
    """

    body: SugarBody
    handlers: tuple[TryExceptArm, ...]
    else_body: SugarBody | None
    finally_body: SugarBody | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Try":
            return False
        finalbody = site.try_finalbody()
        if finalbody is None:
            return True
        return not any(
            isinstance(node, (ast.Return, ast.Raise, ast.Break, ast.Continue))
            for statement in finalbody.node.body
            for node in ast.walk(statement)
        )

    @classmethod
    def new(cls, site, ctx) -> "TrySugar":
        # Body + each handler type (TERM) and body (STATEMENT). Never reduce here.
        arms: list[TryExceptArm] = []
        for handler in site.try_handlers():
            names = handler.except_handler_type_names()
            type_frag = handler.except_handler_type()
            if type_frag is None:
                names = ()
            elif names == ():
                names = None
            arms.append(
                TryExceptArm(
                    type_names=tuple(names) if names is not None else None,
                    type_body=(
                        ctx.build_body(type_frag, SugarRole.TERM)
                        if type_frag is not None
                        else None
                    ),
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
            finally_body=(
                ctx.build_body(site.try_finalbody(), SugarRole.STATEMENT)
                if site.try_finalbody() is not None
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
        dynamic_arm = next(
            (arm for arm in self.handlers if arm.type_names is None), None
        )
        if dynamic_arm is not None:
            from sugar_lift_py_tests.effect import (
                TryHandlerDispatchRuntimeEffect,
                runtime_effect_witness,
            )
            from sugar_lift_py_tests.outcome import Incomplete

            if dynamic_arm.type_body is None:
                from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

                factory_panic_gap(
                    owner="TrySugar",
                    blame=str(self.site),
                    observed="dynamic except handler without type body",
                    requested="runtime handler dispatch operand",
                    fix="construct the handler expression or keep this FactoryPanic",
                )
            return dynamic_arm.type_body.reduce(ctx).and_then(
                lambda operand: Incomplete(
                    TryHandlerDispatchRuntimeEffect(
                        "try handler dispatch runtime boundary: handler type "
                        "expression is not a source-citable Name, Attribute, tuple, "
                        f"or bare catch-all; site={self.site}",
                        witness=runtime_effect_witness(
                            "py.try_handler_dispatch", operand, self.site
                        ),
                    )
                )
            )
        if self.else_body is not None:
            return self._desugar_else(ctx).and_then(
                lambda value: self._sequence_finally(value, ctx)
            )
        # Thread try body, then each guarded handler into one spliced BlockValue.
        return self.body.reduce(ctx).and_then(
            lambda body_val: self._collect_handlers(
                tuple(body_val.contribution()), 0, ctx
            )
        ).and_then(
            lambda value: self._sequence_finally(value, ctx)
        )

    def _collect_handlers(self, accumulated: tuple, index: int, ctx: object) -> Outcome:
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
                [str_const(n) for n in arm.type_names or ()],
            ),
            body=None,
            site=self.site,
        )
        body_ctx = _handler_scope(accumulated, arm, ctx)
        if arm.as_name is not None:
            body_ctx = ScopeRebind(arm.as_name, catch).extend_scope(body_ctx)

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
        """Reduce every face once and guard handler/else contributions."""
        from sugar_lift_py_tests.floor import BlockValue
        from sugar_lift_py_tests.ir import not_, or_
        from sugar_lift_py_tests.outcome import complete_value

        body_value, body_scope = self.body.sugar.reduce_with_scope(ctx)
        entries = list(body_value.contribution())
        guards = []
        for arm in self.handlers:
            guard = _except_guard(arm)
            guards.append(guard)
            handler_ctx = _handler_scope(tuple(entries), arm, ctx)
            handler_value = complete_value(
                arm.body.reduce(handler_ctx), owner="try except handler"
            )
            entries.extend(
                entry.guarded(guard) for entry in handler_value.contribution()
            )
        else_value = complete_value(
            self.else_body.reduce(body_scope), owner="try else body"
        )
        exception_guard = guards[0] if len(guards) == 1 else or_(guards)
        no_exception = not_(exception_guard)
        entries.extend(
            entry.guarded(no_exception) for entry in else_value.contribution()
        )
        return Complete(BlockValue(tuple(entries)))

    def _sequence_finally(self, value, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import BlockValue

        if self.finally_body is None:
            return Complete(value)
        return self.finally_body.reduce(ctx).and_then(
            lambda final: Complete(
                BlockValue(
                    (
                        *value.contribution(),
                        *final.contribution(),
                    )
                )
            )
        )

    def walk_children(self):
        children: list[SugarBody] = [self.body]
        for arm in self.handlers:
            if arm.type_body is not None:
                children.append(arm.type_body)
            children.append(arm.body)
        if self.else_body is not None:
            children.append(self.else_body)
        if self.finally_body is not None:
            children.append(self.finally_body)
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
    from sugar_lift_py_tests.ir import atomic, str_const

    guard = _except_guard(arm)
    out = []
    for entry in entries:
        if type(entry) is ReturnValue:
            out.append(GuardedReturn(guards=(guard,), value=entry.value))
        else:
            out.append(entry)
    return tuple(out)


def _except_guard(arm: TryExceptArm):
    from sugar_lift_py_tests.ir import atomic, str_const

    return atomic("py.except", [str_const(n) for n in arm.type_names or ()])


def _handler_scope(accumulated: tuple, arm: TryExceptArm, fallback):
    """Use the temporal scope captured at the matching raise site.

    A handler observes bindings established before the raise. Searching the
    already-reduced try record preserves that execution-time scope without
    making bindings from later or non-raising paths visible to the handler.
    """
    from sugar_lift_py_tests.floor import GuardedRaise, RaiseValue

    for entry in reversed(accumulated):
        if not isinstance(entry, (RaiseValue, GuardedRaise)):
            continue
        if entry.effect.exception_name not in arm.type_names:
            continue
        if entry.scope is not None:
            return entry.scope
    return fallback
