from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import (
    BlockValue,
    GuardedRaise,
    GuardedReturn,
    RaiseValue,
    ReturnValue,
)
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class ControlFlowGuardOperation:
    method_name: ClassVar[str] = "guard_with"
    guards: tuple
    owner: str = "ControlFlow"
    blame: str = "<unknown>"

    def guard_block(self, receiver: BlockValue, ctx: object) -> Outcome:
        del ctx
        return Complete(
            BlockValue(
                tuple(
                    _with_guards(statement, self.guards)
                    for statement in receiver.statements
                ),
                receiver.fall_through,
            )
        )


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
            guards + statement.guards, statement.effect, statement.scope
        )
    raise TypeError(
        f"write more ControlFlowGuardOperation for `{type(statement).__name__}`"
    )
