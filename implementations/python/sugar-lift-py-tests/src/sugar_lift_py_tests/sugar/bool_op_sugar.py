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
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import and_, or_
        from sugar_lift_py_tests.outcome import Incomplete

        formulas = []
        for operand in self.values:
            out = operand.desugar(ctx)
            if isinstance(out, Incomplete):
                # An operand that is itself an effect propagates -- the boolean is
                # not decidable once a conjunct halts.
                return out
            truth = out.value.truth(self.site)
            formula = getattr(getattr(truth, "value", None), "formula", None)
            if formula is None:
                # A ground-bool operand (no formula) is not lifted yet -- LOUD,
                # never drop a conjunct silently.
                raise NotImplementedError(
                    "boolean operand that folds to a ground boolean is not lifted "
                    f"yet (got {type(getattr(out, 'value', out)).__name__})"
                )
            formulas.append(formula)

        combine = and_ if self.op_kind == "And" else or_
        return Complete(PredicateValue(combine(formulas), self.site))
