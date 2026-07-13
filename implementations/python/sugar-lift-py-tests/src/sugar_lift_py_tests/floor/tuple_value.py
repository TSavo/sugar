from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class TupleValue(FloorValue):
    """A tuple of reduced floor values, in construction order.

    The sugar reduces each element; the floor holds what those reductions were.
    No methods beyond the dataclass -- floors this tuple does not implement panic
    for free via FloorValue defaults.
    """

    elements: tuple

    def to_term(self, *, owner: str):
        # Project each element; vendor digs return tuples (sign/unsign pairs,
        # return_timestamp) that must enter FOL for assert equality.
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "tuple",
            [elt.to_term(owner=owner) for elt in self.elements],
        )

    def truth(self, site):
        # A tuple's truth is nonempty.
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(
            TrueBoolLiteralSugar(site=site)
            if self.elements
            else FalseBoolLiteralSugar(site=site)
        )

    def length(self, site):
        # A tuple knows its length: the count of reduced elements.
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(len(self.elements)))

    def test_python_type(self, value, site):
        return self._collect_type_tests(value, site, 0, ())

    def _collect_type_tests(self, value, site, index, predicates):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        if index >= len(self.elements):
            if not predicates:
                return Complete(FalseBoolLiteralSugar(site=site))
            if len(predicates) == 1:
                return Complete(predicates[0])
            from sugar_lift_py_tests.ir import or_

            return Complete(
                PredicateValue(
                    or_([predicate.formula for predicate in predicates]),
                    site,
                    operand_callsites=tuple(
                        callsite
                        for predicate in predicates
                        for callsite in predicate.operand_callsites
                    ),
                )
            )

        return self.elements[index].test_python_type(value, site).and_then(
            lambda result: self._continue_type_test(
                value, site, index, predicates, result
            )
        )

    def _continue_type_test(self, value, site, index, predicates, result):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if type(result) is TrueBoolLiteralSugar:
            return Complete(TrueBoolLiteralSugar(site=site))
        if type(result) is FalseBoolLiteralSugar:
            return self._collect_type_tests(value, site, index + 1, predicates)
        if type(result) is PredicateValue:
            return self._collect_type_tests(
                value, site, index + 1, (*predicates, result)
            )

        from sugar_lift_py_tests.factory import factory_panic_gap

        factory_panic_gap(
            owner="TupleValue.test_python_type",
            blame=str(site),
            observed=type(result).__name__,
            requested="boolean result from per-element python:type tester",
            fix="implement the element's native python:type tester result",
        )

    def multiply(self, other, site):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.term_value import TermValue

        if type(other) is TermValue and type(other.value) is int:
            from sugar_lift_py_tests.effect import (
                SequenceRepetitionRuntimeEffect,
                runtime_effect_witness,
            )
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            repeated = len(self.elements) * max(other.value, 0)
            if repeated > 65520:
                return Incomplete(
                    SequenceRepetitionRuntimeEffect(
                        "sequence repetition construction boundary: TupleValue "
                        f"would materialize {repeated} literal floor items; "
                        f"site={site}",
                        witness=runtime_effect_witness(
                            "py.sequence_repeat", other, site
                        ),
                    )
                )
            return Complete(TupleValue(self.elements * other.value))
        if type(other) is SymbolicValue:
            from sugar_lift_py_tests.effect import (
                SequenceRepetitionRuntimeEffect,
                runtime_effect_witness,
            )
            from sugar_lift_py_tests.outcome import Incomplete

            return Incomplete(
                SequenceRepetitionRuntimeEffect(
                    "sequence repetition by symbolic count: TupleValue depends "
                    f"on runtime __index__/length semantics; site={site}",
                    witness=runtime_effect_witness(
                        "py.sequence_repeat", other, site
                    ),
                )
            )
        return super().multiply(other, site)

    def subscript(self, index, site):
        # Concrete tuple + in-range TermValue int folds to the element; out of
        # range is IndexError. Non-concrete index stays the py.subscript coordinate.
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        if type(index) is TermValue and type(index.value) is int:
            i = index.value
            n = len(self.elements)
            if -n <= i < n:
                return Complete(self.elements[i])
            from sugar_lift_py_tests.effect import IndexErrorRuntimeEffect

            return Incomplete(
                IndexErrorRuntimeEffect(
                    f"tuple index out of range runtime boundary: "
                    f"index={i} length={n}; owner=TupleValue.subscript site={site}"
                )
            )
        return self.py_subscript_coordinate(index, site)
