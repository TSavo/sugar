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
class _ReducedPath:
    """One reduced execution path that can testify about its terminal scope."""

    record: object
    scope: object
    guard: object | None

    @property
    def continues(self) -> bool:
        return _record_can_fall_through(self.record)


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
                runtime_effect_evidence,
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
                        **runtime_effect_evidence(
                            "py.try_handler_dispatch", operand, self.site
                        ),
                    )
                )
            )
        if self.else_body is not None:
            value = self._desugar_else(ctx)
        else:
            value = self._desugar_without_else(ctx)
        return value.and_then(lambda reduced: self._sequence_finally(reduced, ctx))

    def _desugar_without_else(self, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import BlockValue
        from sugar_lift_py_tests.ir import not_, or_

        body_record, body_scope = _reduce_path(self.body, ctx)
        entries = list(body_record.contribution())
        if not _record_can_fall_through(body_record):
            return self._collect_terminal_handlers(tuple(entries), 0, ctx)
        normal_guard = None
        guards = tuple(_except_guard(arm) for arm in self.handlers)
        normal_guard = not_(guards[0] if len(guards) == 1 else or_(guards))
        paths = [_ReducedPath(body_record, body_scope, normal_guard)]
        handler_entries, handler_paths = self._reduce_handlers(tuple(entries), ctx)
        entries.extend(handler_entries)
        paths.extend(handler_paths)
        scope_entries = _join_continuing_path_scopes(tuple(paths), ctx, self.site)
        return Complete(BlockValue((*entries, *scope_entries)))

    def _collect_terminal_handlers(
        self, accumulated: tuple, index: int, ctx: object
    ) -> Outcome:
        """Preserve the established byte path when the try body cannot continue."""
        from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, ScopeRebind
        from sugar_lift_py_tests.ir import ctor, str_const

        if index >= len(self.handlers):
            return Complete(BlockValue(accumulated))
        arm = self.handlers[index]
        catch = CallSiteValue(
            target_name="except",
            arg_values=(),
            parameters=(),
            term=ctor("py.except", [str_const(n) for n in arm.type_names or ()]),
            body=None,
            site=self.site,
        )
        body_ctx = _handler_scope(accumulated, arm, ctx)
        if arm.as_name is not None:
            body_ctx = ScopeRebind(arm.as_name, catch).extend_scope(body_ctx)
        return arm.body.reduce(body_ctx).and_then(
            lambda hblock: self._collect_terminal_handlers(
                (
                    *accumulated,
                    *_except_arm_contributions(hblock.contribution(), arm),
                ),
                index + 1,
                ctx,
            )
        )

    def _reduce_handlers(self, accumulated: tuple, ctx: object):
        from sugar_lift_py_tests.floor import CallSiteValue, ScopeRebind
        from sugar_lift_py_tests.ir import ctor, str_const

        entries: list[object] = []
        paths: list[_ReducedPath] = []
        scope_source = accumulated
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
            body_ctx = _handler_scope(scope_source, arm, ctx)
            if arm.as_name is not None:
                body_ctx = ScopeRebind(arm.as_name, catch).extend_scope(body_ctx)
            record, final_scope = _reduce_path(arm.body, body_ctx)
            guarded = _except_arm_contributions(record.contribution(), arm)
            entries.extend(guarded)
            scope_source = (*scope_source, *guarded)
            if _record_can_fall_through(record):
                paths.append(_ReducedPath(record, final_scope, _except_guard(arm)))
        return tuple(entries), tuple(paths)

    def _desugar_else(self, ctx: object) -> Outcome:
        """Reduce every face once and guard handler/else contributions."""
        from sugar_lift_py_tests.floor import BlockValue
        from sugar_lift_py_tests.ir import not_, or_

        body_value, body_scope = _reduce_path(self.body, ctx)
        entries = list(body_value.contribution())
        guards = []
        paths = []
        for arm in self.handlers:
            guard = _except_guard(arm)
            guards.append(guard)
            handler_ctx = _handler_scope(tuple(entries), arm, ctx)
            handler_value, handler_scope = _reduce_path(arm.body, handler_ctx)
            entries.extend(
                entry.guarded(guard) for entry in handler_value.contribution()
            )
            if _record_can_fall_through(handler_value):
                paths.append(_ReducedPath(handler_value, handler_scope, guard))
        else_value, else_scope = _reduce_path(self.else_body, body_scope)
        exception_guard = guards[0] if len(guards) == 1 else or_(guards)
        no_exception = not_(exception_guard)
        entries.extend(
            entry.guarded(no_exception) for entry in else_value.contribution()
        )
        if _record_can_fall_through(else_value):
            paths.append(_ReducedPath(else_value, else_scope, no_exception))
        scope_entries = _join_continuing_path_scopes(tuple(paths), ctx, self.site)
        return Complete(BlockValue((*entries, *scope_entries)))

    def _sequence_finally(self, value, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import BlockValue

        if self.finally_body is None:
            return Complete(value)
        final_input = value.extend_scope(ctx)
        final, final_scope = _reduce_path(self.finally_body, final_input)
        final_path = _ReducedPath(final, final_scope, None)
        scope_entries = _join_continuing_path_scopes(
            (final_path,), final_input, self.site
        )
        return Complete(
            BlockValue((*value.contribution(), *final.contribution(), *scope_entries))
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
    """Except-arm exits must not unguard-kill the rest of the outer block.

    Recognition threading splices handler bodies into the enclosing record. An
    unguarded ReturnValue / RaiseValue.follow_rest keeps the tail raw or drops
    it — which would poison asserts *after* a try/except that only exits on the
    exception path. Wrap handler returns as GuardedReturn and raises as
    GuardedRaise under py.except(type) so the tail still reduces.
    """
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.raise_value import RaiseValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    guard = _except_guard(arm)
    out = []
    for entry in entries:
        if type(entry) is ReturnValue:
            out.append(GuardedReturn(guards=(guard,), value=entry.value))
        elif type(entry) is RaiseValue:
            # Bare ``raise`` inside ``except Type`` re-raises the active
            # exception: classify from the handler's source-cited type names
            # so the exceptional-exit coordinate is never unclassified.
            if entry.effect.exception_name is None and arm.type_names:
                from sugar_lift_py_tests.effect import RaiseEffect

                classified = RaiseValue(
                    RaiseEffect(
                        (
                            arm.type_names[0]
                            if len(arm.type_names) == 1
                            else ",".join(arm.type_names)
                        ),
                        entry.effect.blame,
                        entry.effect.source_sha256,
                    ),
                    scope=entry.scope,
                    exception=entry.exception,
                )
                out.append(classified.guarded(guard))
            else:
                out.append(entry.guarded(guard))
        else:
            out.append(entry)
    return tuple(out)


def _reduce_path(body: SugarBody, ctx: object):
    """Reduce normally; materialize a terminal scope only for a continuing path."""
    outcome = body.reduce(ctx)
    assert isinstance(outcome, Complete)
    record = outcome.value
    if not _record_can_fall_through(record):
        return record, ctx
    return body.sugar.reduce_with_scope(ctx)


def _record_can_fall_through(record) -> bool:
    """Whether a reduced path can reach code after the try/except.

    ``follow_rest`` alone is insufficient: a chain of ``if cond: raise`` ends
    with only ``GuardedRaise`` entries, so ``follow_rest`` still continues even
    though every residual path raises. A path falls through only when follow
    continues *and* some non-exit residual remains (or the record is empty /
    pure support).
    """
    if not record.follow_rest().continues:
        return False
    from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
    from sugar_lift_py_tests.floor.guarded_raise import GuardedRaise
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.raise_value import RaiseValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
    from sugar_lift_py_tests.floor.support_value import SupportValue

    exit_types = (ReturnValue, RaiseValue, GuardedReturn, GuardedRaise)
    support_types = (ScopeRebind, SupportValue)

    def flatten(entries: tuple) -> list:
        flat: list = []
        for entry in entries:
            if type(entry) is GuardedFaces:
                flat.extend(flatten(entry.entries))
            else:
                flat.append(entry)
        return flat

    if hasattr(record, "statements"):
        entries = tuple(record.statements)
    else:
        entries = tuple(record.contribution())
    residual = [entry for entry in flatten(entries) if type(entry) not in support_types]
    if not residual:
        return True
    if all(type(entry) in exit_types for entry in residual):
        return False
    return True


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


def _join_continuing_path_scopes(
    paths: tuple[_ReducedPath, ...], incoming, site
) -> tuple:
    """Construct scope effects testified on every reduced continuing path."""
    from sugar_lift_py_tests.floor import GuardedValue, ScopeRebind
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    continuing = tuple(path for path in paths if path.continues)
    if not continuing:
        return ()

    before = {binding.name: binding.value for binding in incoming.temporal.bindings}
    per_path = tuple(
        {binding.name: binding.value for binding in path.scope.temporal.bindings}
        for path in continuing
    )
    common_names = set(per_path[0])
    for bindings in per_path[1:]:
        common_names.intersection_update(bindings)

    entries: list[object] = []
    for name in sorted(common_names):
        values = tuple(bindings[name] for bindings in per_path)
        if all(before.get(name) is value for value in values):
            continue
        if all(value is values[0] for value in values[1:]):
            entries.append(ScopeRebind(name, values[0]))
            continue

        completed_values = []
        effects = []
        for path, value in zip(continuing, values, strict=True):
            outcome = (
                value.answer(path.scope)
                if hasattr(value, "answer")
                else Complete(value)
            )
            if isinstance(outcome, Incomplete):
                effects.append(
                    outcome if path.guard is None else outcome.guarded(path.guard)
                )
                continue
            assert isinstance(outcome, Complete)
            completed_values.append(outcome.value)
        if effects:
            entries.extend(effects)
            continue
        if any(path.guard is None for path in continuing[:-1]):
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="TrySugar.continuing_paths",
                blame=str(site),
                observed=f"unguarded differing binding `{name}`",
                requested="guarded continuing-path temporal join",
                fix=(
                    "construct an exact reduced path guard or keep this " "FactoryPanic"
                ),
            )
        joined = completed_values[-1]
        for path, value in reversed(
            tuple(zip(continuing[:-1], completed_values[:-1], strict=True))
        ):
            joined = GuardedValue(path.guard, value, joined)
        entries.append(ScopeRebind(name, joined))
    return tuple(entries)
