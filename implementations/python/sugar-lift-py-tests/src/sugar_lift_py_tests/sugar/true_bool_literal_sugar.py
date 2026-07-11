from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair

if TYPE_CHECKING:
    from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TrueBoolLiteralSugar(Sugar, role=SugarRole.TERM):
    """The literal `True`. It holds no value -- the boolean IS the type. It is its own
    floor value and it stands on the bool floor as True: it emits the then-face,
    always, with no fork."""

    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "PrimitiveLiteral" and site.literal_value() is True

    @classmethod
    def new(cls, site, ctx) -> "TrueBoolLiteralSugar":
        del ctx  # a literal is a leaf: no children
        return cls(site=site)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="true_bool_literal_return",
            owner_sugar="TrueBoolLiteralSugar",
            body="True",
            truthful="True",
            lying="False",
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
        del else_body
        return then.reduce(ctx)

    def stated(self, site):
        # Ground True states nothing: the assert is support, absorbed.
        del site
        from sugar_lift_py_tests.floor.support_value import SupportValue

        return Complete(SupportValue())

    def negate(self) -> Outcome:
        # True negates to False -- the literal knows its opposite, no fork.
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        return Complete(FalseBoolLiteralSugar(site=self.site))
