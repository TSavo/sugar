from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import BlockValue, GuardedRaise, RaiseValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value

from .control_flow_guard_operation import ControlFlowGuardOperation
from .perform_operation import perform_operation


@dataclass(frozen=True)
class RouteRaisesOperation:
    method_name: ClassVar[str] = "route_raises_with"
    handlers: tuple
    owner: str = "TrySugar"
    blame: str = "<unknown>"

    def route_block_raises(self, receiver: BlockValue, ctx) -> Outcome:
        statements: list[object] = []
        fall_through = list(receiver.fall_through)
        for statement in receiver.statements:
            routed = self._route_statement(statement, ctx)
            if routed is None:
                statements.append(statement)
                continue
            if isinstance(routed, Incomplete):
                return routed
            handled_block = complete_value(routed, owner="raise handler")
            if not isinstance(handled_block, BlockValue):
                raise TypeError("raise handler must produce BlockValue")
            guards = _raise_guards(statement)
            guarded = complete_value(
                perform_operation(
                    owner=self.owner,
                    blame=self.blame,
                    receiver=handled_block,
                    operation=ControlFlowGuardOperation(
                        guards,
                        owner=self.owner,
                        blame=self.blame,
                    ),
                    ctx=ctx,
                ),
                owner="guarded raise handler",
            )
            if not isinstance(guarded, BlockValue):
                raise TypeError("raise handler guard must produce BlockValue")
            statements.extend(guarded.statements)
            if handled_block.fall_through:
                fall_through.append(
                    _guard_conjunction(guards + handled_block.fall_through)
                )
        return Complete(BlockValue(tuple(statements), tuple(fall_through)))

    def _route_statement(self, statement: object, ctx) -> Outcome | None:
        effect = _raise_effect(statement)
        if effect is None:
            return None
        handler_ctx = _raise_scope(statement) or ctx
        for handler in self.handlers:
            if handler.matches(effect):
                return handler.reduce(handler_ctx, effect)
        return None


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
