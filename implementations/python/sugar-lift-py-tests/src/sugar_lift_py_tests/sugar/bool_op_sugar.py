"""Python operand-selecting short-circuit operations ``and`` and ``or``.

Each non-final operand is evaluated once and truth-tested once.  Its stopping
face returns that exact operand; only its continuing face evaluates the next
operand.  The final operand is returned without truth coercion.  A halted truth
dispatch halts the sequence before any later operand is evaluated.
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
    raise SugarNotWritten(
        blame=site,
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
        from sugar_lift_py_tests.outcome import Complete, ExitSet, outcome_to_exitset
        from sugar_lift_py_tests.outcome.exit_set import (
            complement_guard,
            factored_operand,
            false_guard,
            partition,
            true_guard,
        )

        stop_formula = false_guard() if self.op_kind == "And" else true_guard()
        continue_formula = true_guard() if self.op_kind == "And" else false_guard()

        def truth_formula(truth_value):
            from sugar_lift_py_tests.floor.predicate_value import PredicateValue
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            if isinstance(truth_value, TrueBoolLiteralSugar):
                return true_guard()
            if isinstance(truth_value, FalseBoolLiteralSugar):
                return false_guard()
            if isinstance(truth_value, PredicateValue):
                return truth_value.formula

            from sugar_lift_py_tests.gap.info import GapKind, GapLocus
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="BoolOpSugar.truth_formula",
                blame=self.site,
                observed=type(truth_value).__name__,
                requested="a truth-floor boolean or PredicateValue",
                fix=(
                    "make the selected operand's truth floor return its native "
                    "truth value without re-evaluating the operand"
                ),
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )

        def reduce_from(index: int):
            operand = self.values[index]

            # Python returns the final operand; it does not call bool(final).
            if index == len(self.values) - 1:
                return factored_operand(operand.desugar(ctx))

            def project_truth(value):
                formal_coordinate = getattr(value, "formal_coordinate", None)
                if formal_coordinate is not None:
                    from sugar_lift_py_tests.caller_parameter_contract import (
                        NativeOperationExitCarrierV1,
                    )

                    tested = NativeOperationExitCarrierV1.mint(
                        site=self.site,
                        operator="boolop_truth",
                        operands=(value,),
                        coordinates=(formal_coordinate,),
                    )
                else:
                    refuse_undecided_boolean_truth(value, self.site, self.op_kind)
                    tested = value.boolop_truth(self.site)

                return tested.and_then(
                    lambda selection: continue_from(
                        selection.operand, truth_formula(selection.truth_value)
                    )
                )

            def continue_from(value, formula):
                # A decided stopping face never evaluates the RHS at all.
                if formula == stop_formula:
                    return Complete(value)
                if formula == continue_formula:
                    return reduce_from(index + 1)

                # An undecided truth result splits the sequence.  Only the
                # continuing face evaluates the tail; the complement returns
                # the already-evaluated operand itself.
                rhs_guard = (
                    formula if self.op_kind == "And" else complement_guard(formula)
                )
                rhs_face, stop_face = partition(
                    ("BoolOpSugar", str(self.site), index, self.op_kind)
                )
                rhs = outcome_to_exitset(reduce_from(index + 1)).guarded(
                    rhs_guard, rhs_face
                )
                stopped = ExitSet.completed(value, complement_guard(rhs_guard)).guarded(
                    true_guard(), stop_face
                )
                return rhs.union(stopped)

            return factored_operand(operand.desugar(ctx)).and_then(project_truth)

        return reduce_from(0)
