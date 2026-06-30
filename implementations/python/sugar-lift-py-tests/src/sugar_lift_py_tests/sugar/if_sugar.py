from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_if_sugar
from sugar_lift_py_tests.floor import BlockValue, GuardedReturn, ReturnValue
from sugar_lift_py_tests.ir import not_
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


def _guard(stmt, extra: tuple):
    if isinstance(stmt, ReturnValue):
        return GuardedReturn(extra, stmt.value)
    if isinstance(stmt, GuardedReturn):
        return GuardedReturn(extra + stmt.guards, stmt.value)
    raise TypeError(f"if branch yielded a non-return outcome `{type(stmt).__name__}`")


@dataclass(frozen=True)
class IfSugar:
    """An `if` statement composes a test and TWO child blocks: the then-block and the
    else-block. Each branch's returns become GUARDED returns -- the then branch under
    the test, the else branch under its negation. Control flow is the composition of
    child blocks, not a walker; nesting is just blocks within blocks."""

    test: object  # a guard Formula lifted from the `if` test
    then: SugarBody
    else_block: object  # SugarBody | None

    def desugar(self, ctx) -> Outcome:
        then_bv = complete_value(self.then.reduce(ctx), owner="if then-block")
        guarded = [_guard(stmt, (self.test,)) for stmt in then_bv.statements]
        if self.else_block is not None:
            else_bv = complete_value(self.else_block.reduce(ctx), owner="if else-block")
            negated = (not_(self.test),)
            guarded.extend(_guard(stmt, negated) for stmt in else_bv.statements)
            # both branches accounted for -> exhaustive, no fall-through.
            return Complete(BlockValue(tuple(guarded)))
        # no else: execution falls through under `not test` -> the enclosing block
        # guards the statements after this `if` by it.
        return Complete(BlockValue(tuple(guarded), (not_(self.test),)))


def _owns(site) -> bool:
    return site.observed == "If"


IF_CLAIM = SugarClaim(
    name="IfSugar",
    role=SugarRole.STATEMENT,
    owns=_owns,
    build=build_if_sugar,
)
