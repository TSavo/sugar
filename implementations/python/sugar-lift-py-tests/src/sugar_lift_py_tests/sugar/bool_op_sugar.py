"""A boolean operation `a and b`, `a or b` (n-ary: `a and b and c`).

In a boolean context -- a condition, an assertion -- `a and b` is true exactly
when both operands are truthy, `a or b` when either is. So the meaning is the
conjunction / disjunction of the operands' TRUTHINESS: each operand states its
own `truth` predicate (a comparison stands as itself, a bare value emits
`py.truthy`), and this combines them with `and_` / `or_`. One predicate results,
which states as an inv or guards an if exactly like any other predicate.

(Python's `and`/`or` also carry a short-circuit VALUE -- `a and b` evaluates to
`a` when `a` is falsy, else `b`. That value form is not modeled here; the boolean
meaning is what a condition or assertion consumes, and it is what this lifts.)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _boolop_wrapped_pair


@dataclass(frozen=True)
class BoolOpSugar(Sugar):
    op_kind: str  # "And" | "Or"
    values: tuple  # the operand sugars, in source order (>= 2)
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # `(z == 1) and (z != 2)` holds at z == 1 and fails when the asserted
        # value contradicts a conjunct.
        return _boolop_wrapped_pair(
            name="boolop_and",
            owner_sugar="BoolOpSugar",
            truthful="(1 == 1) and (2 == 2)",
            lying="(1 == 1) and (2 == 3)",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from functools import reduce

        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome.exit_set import (
            _and_guards,
            _or_guards,
            factored_operand,
        )
        from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

        # Operands thread through `and_then`, the one door every Outcome variant
        # implements. An operand that halts propagates -- the boolean is not
        # decidable once a conjunct halts -- and an operand that PARTITIONS
        # (`a and (d[k] := f())`, a conjunct whose store can halt) keeps both
        # arms: each completed arm folds its own formula under its own guard.
        # Reading `.value` off the outcome assumed exactly one arm and was the
        # `'ExitSet' object has no attribute 'value'` defect here.
        def collect(operand, collected):
            # One completed arm per operand (#6324): an unfactored partitioning
            # conjunct multiplies the accumulated formula tuple, and k conjuncts
            # distribute into m ** k arms.
            return factored_operand(operand.desugar(ctx)).and_then(
                # Same truth→formula projection as if/if-exp: symbolic formulas
                # stand as themselves; ground True/False (including None.truth →
                # False) fold through true_guard/false_guard. Never raise bare
                # NotImplementedError on a constructible ground boolean.
                lambda value: Complete(
                    (*collected, predicate_formula(value, self.site))
                )
            )

        outcome = Complete(())
        for operand in self.values:
            outcome = outcome.and_then(
                lambda collected, operand=operand: collect(operand, collected)
            )

        # Fold with the shared guard algebra so ground identities absorb:
        #   false ∧ φ → false,  true ∧ φ → φ,  true ∨ φ → true,  false ∨ φ → φ.
        # Raw and_/or_ would leave and_([false, true]) as a connective and hide
        # that None and True is false in boolean context.
        combine = _and_guards if self.op_kind == "And" else _or_guards
        return outcome.and_then(
            lambda formulas: Complete(
                PredicateValue(reduce(combine, formulas), self.site)
            )
        )
