"""`<body> if <test> else <orelse>` -- a conditional EXPRESSION (a value).

This is the value the phi produces: `If.substitution_binding` rewrites a
conditionally-bound name to an `IfExp`, so an `IfExp` lands anywhere a value can
(`return (5 if c else 6)`, `assert (5 if c else 6) == x`, `(5 if c else 6) + 1`).

The value is a `GuardedValue(guard, when_true, when_false)` -- the SAME conditional
floor value the predicate join bindings already produce. It is not an ite term:
operations DISTRIBUTE into both arms (`GuardedValue._map`) and a return/equality
splits into `(c -> out == then) AND (not c -> out == else)` via `post_formula` /
`equals`, each arm's equality resolved PER ATOM by `resolve_equality_atom`. So the
"what one sort is the conditional" question never forms -- the value resolves
itself, and a mixed Int/Real conditional is two per-atom equalities each carrying
its own `to_real` bridge, never a single mixed-sort term. (Only a genuinely
opaque collapse -- the conditional as an argument to an EUF function -- folds to
a `py.conditional` term; there an integer arm promotes to Real, since 5 == 5.0.)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair
from sugar_lift_py_tests.sugar.if_sugar import predicate_formula


@dataclass(frozen=True)
class IfExpSugar(Sugar):
    """`<body> if <test> else <orelse>`, constructed by `IfExp.sugar()` with the
    test's and both arms' sugars already built."""

    test: Sugar
    body: Sugar  # the then-value
    orelse: Sugar  # the else-value
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        # A conditional return: the post distributes to z == 1 -> out == 10, so
        # the caller's A(1) == 10 discharges and A(1) == 11 contradicts.
        return _call_return_pair(
            name="ifexp_conditional_return",
            owner_sugar="IfExpSugar",
            body="10 if z == 1 else 20",
            truthful="10",
            lying="11",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.outcome import Incomplete

        cond = self.test.desugar(ctx)
        # The guard is the test's TRUTHINESS as a predicate -- uniform via
        # `.truth`: a predicate test (`5 if a == b else 6`) stands as its formula,
        # a bare value (`5 if c else 6`) emits `py.truthy(c)`. A ground-bool test
        # folds to a literal with no formula and is not lifted yet -- LOUD.
        formula = predicate_formula(cond.value, self.site)

        then_out = self.body.desugar(ctx)
        else_out = self.orelse.desugar(ctx)
        # An arm that is itself an effect (an unresolvable call, a halt) is not a
        # value to guard-join yet: be loud rather than fold an effect into a value.
        if isinstance(then_out, Incomplete) or isinstance(else_out, Incomplete):
            raise NotImplementedError(
                "a conditional-expression arm that reduces to an effect is not "
                "lifted yet: both arms must be values to form the guarded value"
            )

        return Complete(GuardedValue(formula, then_out.value, else_out.value))
