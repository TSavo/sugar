from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair

if TYPE_CHECKING:
    from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class FalseBoolLiteralSugar(Sugar, FloorValue, role=SugarRole.TERM):
    """The literal `False`. It holds no value -- the boolean IS the type. It is its own
    floor value and it dispatches the emit to the else-face; with no else it emits
    nothing (an empty block adds no constraint). No fork.

    Inherits FloorValue so unimplemented floor verbs (unary_minus, etc.) and
    as_expression_statement panic or discard cleanly -- never AttributeError.
    """

    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "PrimitiveLiteral" and site.literal_value() is False

    @classmethod
    def new(cls, site, ctx) -> "FalseBoolLiteralSugar":
        del ctx  # a literal is a leaf: no children
        return cls(site=site)

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

    def truth(self, site):
        # A bool's truth is itself.
        del site
        return Complete(self)

    def binary_conditional(
        self,
        then: "SugarBody",
        else_body: "SugarBody | None",
        ctx: object = None,
        site=None,
    ) -> Outcome:
        del then, site
        if else_body is None:
            return Complete(BlockValue(()))
        return else_body.reduce(ctx)

    def stated(self, site):
        # Ground False under assert is a recognized fact the program halts --
        # a named runtime effect, per the gap/fact discriminator; never a panic.
        from sugar_lift_py_tests.effect import AssertionFailedRuntimeEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            AssertionFailedRuntimeEffect(
                f"assertion failed runtime boundary: the condition is concretely "
                f"False; owner=FalseBoolLiteralSugar site={site}"
            )
        )

    def negate(self) -> Outcome:
        # False negates to True -- the literal knows its opposite, no fork.
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(TrueBoolLiteralSugar(site=self.site))

    def is_identical(self, other, site):
        # False is a singleton: False is False folds True; False is True folds
        # False. Anything else emits identity (the general case).
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if type(other) is FalseBoolLiteralSugar:
            return Complete(TrueBoolLiteralSugar(site=site))
        if type(other) is TrueBoolLiteralSugar:
            return Complete(FalseBoolLiteralSugar(site=site))
        from sugar_lift_py_tests.floor.floor_value import FloorValue

        return FloorValue.is_identical(self, other, site)

    def callsites(self):
        return ()

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import bool_const

        return bool_const(False)

