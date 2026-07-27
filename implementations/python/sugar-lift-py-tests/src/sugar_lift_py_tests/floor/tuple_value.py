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

    def denotes_value(self) -> bool:
        """This floor value denotes a ``tuple``."""
        return True

    def attribute(self, name, site):
        # Bound methods and fields on a constructed tuple (``().count``, ``t.index``) stay the
        # py.getattr coordinate -- one law, shared with StringValue and the
        # other constructed containers. Never invent a method body or a field.
        del site
        from sugar_lift_py_tests.floor.getattr_coordinate import getattr_coordinate

        return getattr_coordinate(self, name, owner="TupleValue.attribute")

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

    def is_identical(self, other, site):
        from sugar_lift_py_tests.floor.none_value import NoneValue

        if type(other) is NoneValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return Complete(FalseBoolLiteralSugar(site=site))
        return super().is_identical(other, site)

    def length(self, site):
        # A tuple knows its length: the count of reduced elements.
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(len(self.elements)))

    def project_sequence_with(self, operation, ctx):
        """Unpack against authenticated reduced members already in hand.

        ``TupleValue.elements`` is the finite member testimony from construction;
        SequenceProjectionOperation binds names only when arity matches.
        """
        return operation.project_tuple(self, ctx)

    @property
    def items(self) -> tuple:
        """Member sequence for SequenceProjectionOperation.project_tuple."""
        return self.elements

    def contains(self, item, site):
        # A guarded needle is not one needle: distribute into its faces and
        # rejoin under the same guard before this receiver's own law runs.
        from sugar_lift_py_tests.floor.guarded_operand import (
            distribute_guarded_predicate,
        )

        distributed = distribute_guarded_predicate(self, item, "contains", site)
        if distributed is not None:
            return distributed
        # Membership over a constructed tuple: same closed-equality law as
        # ListValue / SetValue — fold, emit typed obligation, or stay loud.
        from sugar_lift_py_tests.floor.set_value import (
            _bool_result,
            _closed_member_equal,
        )

        decisions = tuple(
            _closed_member_equal(item, element) for element in self.elements
        )
        if any(decision is True for decision in decisions):
            return _bool_result(True, site)
        if all(decision is False for decision in decisions):
            return _bool_result(False, site)
        if any(decision is None for decision in decisions):
            from sugar_lift_py_tests.floor.predicate_value import PredicateValue
            from sugar_lift_py_tests.ir import atomic
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                PredicateValue(
                    atomic(
                        "python.tuple.contains",
                        [
                            item.to_term(owner="python.tuple.contains member"),
                            self.to_term(owner="python.tuple.contains tuple"),
                        ],
                    ),
                    site,
                    operand_callsites=(*item.callsites(), *self.callsites()),
                )
            )
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="TupleValue.contains",
            blame=str(site),
            observed=type(item).__name__,
            requested="constructed finite member or typed symbolic membership operand",
            fix="construct member equality on the Python floor or keep it loud",
        )

    def add(self, other, site):
        if type(other) is TupleValue:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TupleValue((*self.elements, *other.elements)))
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.import_alias_value import ImportAliasValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) in (CallSiteValue, ImportAliasValue, SymbolicValue):
            return SymbolicValue(self.to_term(owner=str(site))).add(other, site)
        return super().add(other, site)

    def test_python_type(self, value, site):
        return self._collect_type_tests(value, site, 0, ())

    def test_python_subtype(self, subtype, site):
        return self._collect_subtype_tests(subtype, site, 0, ())

    def _collect_subtype_tests(self, subtype, site, index, predicates):
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
                    or_([predicate.formula for predicate in predicates]), site
                )
            )
        return subtype.test_python_subtype(self.elements[index], site).and_then(
            lambda result: self._continue_subtype_test(
                subtype, site, index, predicates, result
            )
        )

    def _continue_subtype_test(self, subtype, site, index, predicates, result):
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
            return self._collect_subtype_tests(subtype, site, index + 1, predicates)
        if type(result) is PredicateValue:
            return self._collect_subtype_tests(
                subtype, site, index + 1, (*predicates, result)
            )
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="TupleValue.test_python_subtype",
            blame=str(site),
            observed=type(result).__name__,
            requested="boolean or typed subtype obligation",
            fix="implement the tuple arm on the Python subtype floor",
        )

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

        return (
            self.elements[index]
            .test_python_type(value, site)
            .and_then(
                lambda result: self._continue_type_test(
                    value, site, index, predicates, result
                )
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

        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="TupleValue.test_python_type",
            blame=str(site),
            observed=type(result).__name__,
            requested="boolean result from per-element python:type tester",
            fix="implement the element's native python:type tester result",
        )

    def multiply(self, other, site):
        # Python tuple repetition, through the one sequence-repetition law.
        from sugar_lift_py_tests.floor.sequence_repetition import repeat_sequence

        return repeat_sequence(
            self, other, site, elements=self.elements, rebuild=TupleValue
        )

    def subscript(self, index, site):
        # Concrete tuple + integer index is fully decided. A known non-integer
        # is TypeError; an index with undecided runtime semantics stays loud.
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        if type(index) is TermValue and isinstance(index.value, int):
            i = index.value
            n = len(self.elements)
            if -n <= i < n:
                return Complete(self.elements[i])
            from sugar_lift_py_tests.floor.ground_index_error import (
                ground_index_error,
            )

            return ground_index_error(
                owner="TupleValue.subscript",
                operation="tuple subscript",
                index=i,
                length=n,
                site=site,
            )
        if type(index) is TermValue:
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError", site=site, owner="TupleValue.subscript"
            )
        return self.undecided_subscript(index, site, owner="TupleValue.subscript")
