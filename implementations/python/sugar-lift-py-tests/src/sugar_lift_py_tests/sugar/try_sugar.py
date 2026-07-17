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
            else (
                self.type_names[0]
                if len(self.type_names) == 1
                else ",".join(self.type_names)
            )
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
                    blame=self.site,
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
        # Thread try body + handlers, then project definite post-try bindings
        # the way if/else projects surviving/joined faces (#4190).
        return self._desugar_handlers(ctx).and_then(
            lambda value: self._sequence_finally(value, ctx)
        )

    def _desugar_handlers(self, ctx: object) -> Outcome:
        """Reduce try body and handlers; project definite bindings past the try.

        Assignment in the try body is support (ScopeRebind contribution is empty),
        so splicing ``body.contribution()`` alone drops names for the enclosing
        block. Mirror PredicateValue's branch join: when every handler exits and
        the body does not, the body's new bindings survive; when neither face
        exits, names present on every surviving face join; when only handlers
        survive, take the handler face bindings.
        """
        from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, ScopeRebind
        from sugar_lift_py_tests.ir import ctor, str_const

        body_value, body_scope = _reduce_with_scope(self.body, ctx)
        entries = list(body_value.contribution())
        body_exits = _face_exits(entries)

        handler_scopes: list[object] = []
        handler_exit_flags: list[bool] = []
        for arm in self.handlers:
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
            body_ctx = _handler_scope(tuple(entries), arm, ctx)
            if arm.as_name is not None:
                body_ctx = ScopeRebind(arm.as_name, catch).extend_scope(body_ctx)
            handler_value, handler_scope = _reduce_with_scope(arm.body, body_ctx)
            handler_entries = tuple(handler_value.contribution())
            handler_exit_flags.append(_face_exits(handler_entries))
            handler_scopes.append(handler_scope)
            entries.extend(_except_arm_contributions(handler_entries, arm))

        rebinds = _post_try_rebinds(
            body_scope=body_scope,
            body_exits=body_exits,
            handler_scopes=tuple(handler_scopes),
            handler_exit_flags=tuple(handler_exit_flags),
            before_ctx=ctx,
        )
        return Complete(BlockValue((*entries, *rebinds)))

    def _desugar_else(self, ctx: object) -> Outcome:
        """Reduce every face once and guard handler/else contributions."""
        from sugar_lift_py_tests.floor import BlockValue
        from sugar_lift_py_tests.ir import not_, or_

        body_value, body_scope = _reduce_with_scope(self.body, ctx)
        entries = list(body_value.contribution())
        body_exits = _face_exits(entries)
        guards = []
        handler_scopes: list[object] = []
        handler_exit_flags: list[bool] = []
        for arm in self.handlers:
            guard = _except_guard(arm)
            guards.append(guard)
            handler_ctx = _handler_scope(tuple(entries), arm, ctx)
            handler_value, handler_scope = _reduce_with_scope(arm.body, handler_ctx)
            handler_entries = tuple(handler_value.contribution())
            handler_exit_flags.append(_face_exits(handler_entries))
            handler_scopes.append(handler_scope)
            entries.extend(entry.guarded(guard) for entry in handler_entries)
        else_value, else_scope = _reduce_with_scope(self.else_body, body_scope)
        else_entries = tuple(else_value.contribution())
        else_exits = _face_exits(else_entries)
        exception_guard = guards[0] if len(guards) == 1 else or_(guards)
        no_exception = not_(exception_guard)
        entries.extend(entry.guarded(no_exception) for entry in else_entries)
        # Success face is try-body scope extended by else; handler faces are the
        # exception arms. Project definite post-try bindings across those faces.
        success_exits = body_exits or else_exits
        rebinds = _post_try_rebinds(
            body_scope=else_scope,
            body_exits=success_exits,
            handler_scopes=tuple(handler_scopes),
            handler_exit_flags=tuple(handler_exit_flags),
            before_ctx=ctx,
        )
        return Complete(BlockValue((*entries, *rebinds)))

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


def _reduce_with_scope(body: SugarBody, ctx: object):
    """Reduce a statement body once, returning the record and terminal context."""
    from sugar_lift_py_tests.outcome import complete_value

    sugar = body.sugar
    if hasattr(sugar, "reduce_with_scope"):
        return sugar.reduce_with_scope(ctx)
    outcome = body.reduce(ctx)
    value = complete_value(outcome, owner="try face")
    return value, outcome.extend_scope(ctx)


def _face_exits(entries: tuple) -> bool:
    return any(entry.post_contribution() for entry in entries)


def _post_try_rebinds(
    *,
    body_scope: object,
    body_exits: bool,
    handler_scopes: tuple,
    handler_exit_flags: tuple[bool, ...],
    before_ctx: object,
) -> tuple:
    """ScopeRebind entries that must ride past the try for the enclosing block.

    Matches if/else definite-assignment geometry (PredicateValue branch join):
    - every handler exits and body falls through -> body's new bindings survive
    - body exits and no handler exits -> handler face bindings survive
    - neither side fully exits -> names present on every surviving face join
    """
    if not handler_scopes:
        if body_exits:
            return ()
        return _surviving_rebinds(body_scope, before_ctx)

    all_handlers_exit = all(handler_exit_flags)
    any_handler_exits = any(handler_exit_flags)

    if not body_exits and all_handlers_exit:
        return _surviving_rebinds(body_scope, before_ctx)

    if body_exits and not any_handler_exits:
        if len(handler_scopes) == 1:
            return _surviving_rebinds(handler_scopes[0], before_ctx)
        return _join_rebinds(handler_scopes, before_ctx)

    if not body_exits and not any_handler_exits:
        return _join_rebinds((body_scope, *handler_scopes), before_ctx)

    # Mixed handler exits with a non-exiting body: only names still definite on
    # the body face and every non-exiting handler face survive.
    surviving_handler_scopes = tuple(
        scope
        for scope, exits in zip(handler_scopes, handler_exit_flags)
        if not exits
    )
    if not body_exits and surviving_handler_scopes:
        return _join_rebinds((body_scope, *surviving_handler_scopes), before_ctx)
    return ()


def _surviving_rebinds(surviving_scope: object, before_ctx: object) -> tuple:
    from sugar_lift_py_tests.floor import ScopeRebind
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    before = {binding.name: binding.value for binding in before_ctx.temporal.bindings}
    surviving = {
        binding.name: binding.value for binding in surviving_scope.temporal.bindings
    }
    rebinds = []
    for name, binding in sorted(surviving.items()):
        if before.get(name) is binding:
            continue
        answer = binding.answer(surviving_scope)
        if isinstance(answer, Incomplete):
            continue
        assert isinstance(answer, Complete)
        rebinds.append(ScopeRebind(name, answer.value))
    return tuple(rebinds)


def _join_rebinds(scopes: tuple, before_ctx: object) -> tuple:
    from sugar_lift_py_tests.floor import ScopeRebind
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    if not scopes:
        return ()
    if len(scopes) == 1:
        return _surviving_rebinds(scopes[0], before_ctx)

    before = {binding.name: binding.value for binding in before_ctx.temporal.bindings}
    face_maps = [
        {binding.name: binding.value for binding in scope.temporal.bindings}
        for scope in scopes
    ]
    common = set(face_maps[0])
    for face in face_maps[1:]:
        common &= set(face)
    rebinds = []
    for name in sorted(common):
        face_bindings = [face[name] for face in face_maps]
        if all(before.get(name) is binding for binding in face_bindings):
            continue
        answers = []
        incomplete = False
        for scope, binding in zip(scopes, face_bindings):
            answer = binding.answer(scope)
            if isinstance(answer, Incomplete):
                incomplete = True
                break
            assert isinstance(answer, Complete)
            answers.append(answer.value)
        if incomplete:
            continue
        # Every surviving face bound the name. Prefer the first face (try body /
        # first handler) as the post-try coordinate; branch-local record entries
        # already carry polarity under py.except guards.
        rebinds.append(ScopeRebind(name, answers[0]))
    return tuple(rebinds)
