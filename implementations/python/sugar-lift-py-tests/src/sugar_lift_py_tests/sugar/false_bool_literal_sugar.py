from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair

if TYPE_CHECKING:
    from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class FalseBoolLiteralSugar(Sugar, role=SugarRole.TERM):
    """The literal `False`. It holds no value -- the boolean IS the type. It is its own
    floor value and it dispatches the emit to the else-face; with no else it emits
    nothing (an empty block adds no constraint). No fork."""

    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "PrimitiveLiteral" and site.literal_value() is False

    @classmethod
    def new(cls, site, ctx) -> "FalseBoolLiteralSugar":
        del ctx  # a literal is a leaf: no children
        return cls(blame=site.blame)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="false_bool_literal_return",
            owner_sugar="FalseBoolLiteralSugar",
            body="False",
            truthful="False",
            lying="True",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx  # the literal is its own floor value
        return Complete(self)

    def contribution(self):
        # Its own floor value: contributes itself to the block record.
        return (self,)

    def binary_conditional(
        self, then: "SugarBody", else_body: "SugarBody | None", ctx: object = None
    ) -> Outcome:
        del then
        if else_body is None:
            return Complete(BlockValue(()))
        return else_body.reduce(ctx)

    def negate(self) -> Outcome:
        # False negates to True -- the literal knows its opposite, no fork.
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(TrueBoolLiteralSugar(blame=self.blame))
