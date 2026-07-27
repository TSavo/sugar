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

_BOOL_OPERATOR_COORDINATE = {
    "And": "and",
    "Or": "or",
}


def refuse_undecided_boolean_truth(value, site, op_kind: str) -> None:
    """Keep undecided ``bool(operand)`` dispatch loud at the BoolOp producer.

    Python evaluates ``a and b`` / ``a or b`` by first taking the truth of an
    operand.  When that operand denotes a value but its runtime type is
    undecided, native ``__bool__`` / ``__len__`` may complete or raise
    (``Series`` raises ``ValueError``).  Emitting ``py.truthy`` invents a total
    completion; inventing ``ValueError`` invents an exception identity.  Both
    stay refused until source-visible type testimony decides.
    """
    denotes = getattr(value, "denotes_value", None)
    decided = getattr(value, "runtime_type_is_decided", None)
    if not callable(denotes) or not callable(decided):
        return
    if not denotes() or decided():
        return

    from sugar_source_tree.panic import SugarNotWritten

    operator = _BOOL_OPERATOR_COORDINATE[op_kind]
    del site
    raise SugarNotWritten(
        owner="boolean_operation_exception_floor",
        observed=f"{type(value).__name__} {operator}",
        requested=(
            "source-visible native truth testimony selecting completion "
            "or an authenticated exceptional exit"
        ),
        fix=(
            "preserve the undecided third value at the BoolOp producer; "
            "resolve native operand types and their __bool__/__len__ bodies "
            "from source, or retain this named refusal without inventing an "
            "exception identity"
        ),
    )


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
        from sugar_lift_py_tests.outcome import Complete, ExitSet, outcome_to_exitset
        from sugar_lift_py_tests.outcome.exit_set import (
            Completed,
            _and_guards,
            _or_guards,
            complement_guard,
            factored_operand,
            false_guard,
            partition,
            true_guard,
        )
        from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

        combine = _and_guards if self.op_kind == "And" else _or_guards
        stop_formula = false_guard() if self.op_kind == "And" else true_guard()

        def reduce_from(index: int):
            operand = self.values[index]

            def project_truth(value):
                refuse_undecided_boolean_truth(value, self.site, self.op_kind)
                return Complete(predicate_formula(value, self.site))

            standing = factored_operand(operand.desugar(ctx)).and_then(project_truth)

            def continue_from(formula):
                last = index == len(self.values) - 1
                if last:
                    return Complete(PredicateValue(formula, self.site))

                # A decided stopping face never evaluates the RHS at all.
                if formula == stop_formula:
                    return Complete(PredicateValue(stop_formula, self.site))
                if (self.op_kind == "And" and formula == true_guard()) or (
                    self.op_kind == "Or" and formula == false_guard()
                ):
                    return reduce_from(index + 1)

                tail = reduce_from(index + 1)
                tail_es = outcome_to_exitset(tail)
                halted = any(not isinstance(edge, Completed) for edge in tail_es.exits)

                # If construction established that every RHS face completes,
                # its truth formula is available and the ordinary boolean
                # formula remains a single value.  No exceptional edge is being
                # hidden in this arm.
                if not halted and len(tail_es.exits) == 1:
                    tail_value = tail_es.exits[0].value
                    return Complete(
                        PredicateValue(combine(formula, tail_value.formula), self.site)
                    )

                # Otherwise Python evaluates the tail only on this face.  The
                # complementary face completes with the short-circuit result;
                # the RHS halt is conditional, never promoted to unconditional
                # and never discarded as absent.
                rhs_guard = (
                    formula if self.op_kind == "And" else complement_guard(formula)
                )
                rhs_face, stop_face = partition(
                    ("BoolOpSugar", str(self.site), index, self.op_kind)
                )
                rhs = tail_es.guarded(rhs_guard, rhs_face)
                stopped = ExitSet.completed(
                    PredicateValue(stop_formula, self.site),
                    complement_guard(rhs_guard),
                ).guarded(true_guard(), stop_face)
                return rhs.union(stopped)

            return standing.and_then(continue_from)

        return reduce_from(0)
