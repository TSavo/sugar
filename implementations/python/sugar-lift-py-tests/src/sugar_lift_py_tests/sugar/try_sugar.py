from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RaiseEffect, RuntimeEffect
from sugar_lift_py_tests.floor import (
    BlockValue,
    GuardedRaise,
    GuardedReturn,
    RaiseValue,
    ReturnValue,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.try_handler import TryHandler
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TrySugar(Sugar, role=SugarRole.STATEMENT):
    body: SugarBody
    handlers: tuple[TryHandler, ...]
    else_body: SugarBody | None
    finally_body: SugarBody | None
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.body, SugarBody):
            raise TypeError("TrySugar body must be factory-built")
        if self.else_body is not None and not isinstance(self.else_body, SugarBody):
            raise TypeError("TrySugar else body must be factory-built")
        if self.finally_body is not None and not isinstance(
            self.finally_body, SugarBody
        ):
            raise TypeError("TrySugar finally body must be factory-built")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed in {"Try", "TryStar"}

    @classmethod
    def build(cls, site, ctx) -> "TrySugar":
        if site.observed not in {"Try", "TryStar"}:
            raise TypeError("TrySugar claim built a non-try statement")
        return cls(
            body=ctx.build_body(site.try_body(), SugarRole.STATEMENT),
            handlers=tuple(
                TryHandler(
                    exception_names=handler.except_handler_type_names(),
                    bound_name=handler.except_handler_name(),
                    body=ctx.build_body(
                        handler.except_handler_body(), SugarRole.STATEMENT
                    ),
                    blame=handler.blame,
                )
                for handler in site.try_handlers()
            ),
            else_body=_build_optional(site.try_orelse(), ctx),
            finally_body=_build_optional(site.try_finalbody(), ctx),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        exit_outcome = self._try_exit(ctx)
        if self.finally_body is None:
            return exit_outcome
        return _apply_finally(exit_outcome, self.finally_body, ctx)

    def _try_exit(self, ctx) -> Outcome:
        outcome = self.body.reduce(ctx)
        if isinstance(outcome, Incomplete):
            return self._route_incomplete(outcome, ctx)
        block = complete_value(outcome, owner="try body")
        routed = self._route_block_raises(block, ctx)
        if isinstance(routed, Incomplete):
            return routed
        block = complete_value(routed, owner="try routed body")
        if self.else_body is not None and _runs_else(block):
            return self.else_body.reduce(ctx)
        return Complete(block)

    def _route_incomplete(self, outcome: Incomplete, ctx) -> Outcome:
        effect = outcome.effect
        if not isinstance(effect, RaiseEffect):
            return outcome
        for handler in self.handlers:
            if handler.matches(effect):
                return handler.reduce(ctx, effect)
        return outcome

    def _route_block_raises(self, block: BlockValue, ctx) -> Outcome:
        statements: list[object] = []
        fall_through = list(block.fall_through)
        for statement in block.statements:
            routed = self._route_raise_statement(statement, ctx)
            if routed is None:
                statements.append(statement)
                continue
            if isinstance(routed, Incomplete):
                return routed
            handled_block = complete_value(routed, owner="try handler")
            guards = _raise_guards(statement)
            statements.extend(
                _with_guards(handled_statement, guards)
                for handled_statement in handled_block.statements
            )
            if handled_block.fall_through:
                fall_through.append(
                    _guard_conjunction(guards + handled_block.fall_through)
                )
        return Complete(BlockValue(tuple(statements), tuple(fall_through)))

    def _route_raise_statement(self, statement: object, ctx) -> Outcome | None:
        effect = _raise_effect(statement)
        if effect is None:
            return None
        handler_ctx = _raise_scope(statement) or ctx
        for handler in self.handlers:
            if handler.matches(effect):
                return handler.reduce(handler_ctx, effect)
        return None


def _build_optional(site, ctx) -> SugarBody | None:
    if site is None:
        return None
    return ctx.build_body(site, SugarRole.STATEMENT)


def _runs_else(block: BlockValue) -> bool:
    return not block.statements


def _apply_finally(incoming: Outcome, finally_body: SugarBody, ctx) -> Outcome:
    outcome = finally_body.reduce(ctx)
    if isinstance(outcome, Incomplete):
        return outcome
    final_block = complete_value(outcome, owner="try finally")
    if not final_block.statements:
        return incoming
    if not final_block.fall_through:
        return Complete(final_block)
    if isinstance(incoming, Incomplete):
        return Incomplete(
            RuntimeEffect(
                "finally guarded return over incomplete incoming exit: add guarded "
                "effect exit joining before lowering this TrySugar shape"
            )
        )
    incoming_block = complete_value(incoming, owner="try incoming exit")
    return Complete(_merge_finally_fallthrough(final_block, incoming_block))


def _merge_finally_fallthrough(
    final_block: BlockValue, incoming_block: BlockValue
) -> BlockValue:
    guarded = list(final_block.statements)
    guarded.extend(
        _with_guards(statement, final_block.fall_through)
        for statement in incoming_block.statements
    )
    return BlockValue(tuple(guarded))


def _with_guards(statement, guards: tuple):
    if isinstance(statement, ReturnValue):
        return GuardedReturn(guards, statement.value) if guards else statement
    if isinstance(statement, GuardedReturn):
        return GuardedReturn(guards + statement.guards, statement.value)
    if isinstance(statement, RaiseValue):
        return (
            GuardedRaise(guards, statement.effect, statement.scope)
            if guards
            else statement
        )
    if isinstance(statement, GuardedRaise):
        return GuardedRaise(
            guards + statement.guards,
            statement.effect,
            statement.scope,
        )
    raise TypeError(
        f"write more TrySugar finally fallthrough for `{type(statement).__name__}`"
    )


def _raise_effect(statement: object) -> RaiseEffect | None:
    if isinstance(statement, RaiseValue):
        return statement.effect
    if isinstance(statement, GuardedRaise):
        return statement.effect
    return None


def _raise_guards(statement: object) -> tuple:
    if isinstance(statement, GuardedRaise):
        return statement.guards
    return ()


def _raise_scope(statement: object):
    if isinstance(statement, (RaiseValue, GuardedRaise)):
        return statement.scope
    return None


def _guard_conjunction(guards: tuple):
    if len(guards) == 1:
        return guards[0]
    from sugar_lift_py_tests.ir import and_

    return and_(list(guards))
