from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor.guard_stable_value import GuardStableValue
from sugar_lift_py_tests.outcome import ExitSet, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class TrueBoolLiteralSugar(ConstructedTermSugar, GuardStableValue):
    """The literal `True`. It holds no value -- the boolean IS the type. It is its own
    floor value and it stands on the bool floor as True: it emits the then-face,
    always, with no fork.

    Inherits FloorValue so unimplemented floor verbs (unary_minus, etc.) and
    as_expression_statement panic or discard cleanly -- never AttributeError.
    """

    site: object = dataclass_field(compare=False)

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
        return ExitSet.completed(self)

    def contribution(self):
        # Its own floor value: contributes itself to the block record.
        return (self,)

    def truth(self, site):
        # A bool's truth is itself.
        del site
        return ExitSet.completed(self)

    def stated(self, site):
        # An assert always states its fact. A test the floor decided True
        # states the decided fact: truth, the constant that is all this value
        # has. Its row says the assertion is reached and holds (#7766).
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.outcome.exit_set import true_guard

        return ExitSet.completed(InvValue(true_guard(), site))

    def negate(self) -> Outcome:
        # True negates to False -- the literal knows its opposite, no fork.
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        return ExitSet.completed(FalseBoolLiteralSugar(site=self.site))

    def add(self, other, site, ctx):
        # Python bool is a closed integer subtype: True contributes exactly
        # one, then the ordinary numeric floor decides the peer.
        from sugar_lift_py_tests.floor.term_value import TermValue

        return TermValue(1).add(other, site, ctx)

    def subtract(self, other, site, ctx):
        from sugar_lift_py_tests.floor.term_value import TermValue

        return TermValue(1).subtract(other, site, ctx)

    def unary_minus(self, site):
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue

        return ExitSet.completed(TermValue(-1))

    def bitwise_and(self, other, site, ctx):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        if type(other) is PredicateValue:
            return ExitSet.completed(other)
        if type(other) is TrueBoolLiteralSugar:
            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        if type(other) is FalseBoolLiteralSugar:
            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        return super().bitwise_and(other, site, ctx)

    def bitwise_invert(self, site):
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue

        return ExitSet.completed(TermValue(-2))

    def bitwise_xor(self, other, site, ctx):
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        if type(other) is TrueBoolLiteralSugar:
            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        if type(other) is FalseBoolLiteralSugar:
            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        return super().bitwise_xor(other, site, ctx)

    def is_identical(self, other, site):
        # True is a singleton: True is True folds True; True is False folds False.
        # Anything else emits identity (the general case).
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        if type(other) is TrueBoolLiteralSugar:
            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        if type(other) is FalseBoolLiteralSugar:
            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        from sugar_lift_py_tests.floor.floor_value import FloorValue

        return FloorValue.is_identical(self, other, site)

    def callsites(self):
        return ()

    def denotes_value(self) -> bool:
        """This floor value denotes ``True``."""
        return True

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import bool_const

        return bool_const(True)
