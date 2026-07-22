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

        from sugar_lift_py_tests.gap.panic import factory_panic_gap

        factory_panic_gap(
            owner="TupleValue.test_python_type",
            blame=str(site),
            observed=type(result).__name__,
            requested="boolean result from per-element python:type tester",
            fix="implement the element's native python:type tester result",
        )

    def multiply(self, other, site):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.import_alias_value import ImportAliasValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.term_value import TermValue

        if (
            type(other) is CallSiteValue
            and other.target_name == "MAXDIMS"
            and len(other.arg_values) == 1
            and type(other.arg_values[0]) is ImportAliasValue
            and (
                other.arg_values[0].name == "numpy._core._multiarray_umath"
                or other.arg_values[0].import_target == "numpy._core._multiarray_umath"
            )
        ):
            # NumPy 2.x publishes NPY_MAXDIMS as the source-owned MAXDIMS
            # module constant. This is a static vendor pin, not a runtime count.
            other = TermValue(64)
        if type(other) is TermValue and type(other.value) is int:
            from sugar_lift_py_tests.outcome import Complete

            repeated = len(self.elements) * max(other.value, 0)
            from sugar_lift_py_tests.sugar.for_sugar import (
                STATIC_UNFOLD_LIMIT,
                finite_unfold_cap_panic,
            )

            if repeated > STATIC_UNFOLD_LIMIT:
                finite_unfold_cap_panic(
                    construction="TupleValue repetition",
                    site=site,
                    observed=f"tuple repetition cardinality={repeated}",
                    limit=STATIC_UNFOLD_LIMIT,
                )
            return Complete(TupleValue(self.elements * other.value))
        runtime_count_kind = None
        if type(other) is SymbolicValue:
            runtime_count_kind = "symbolic count"
        elif type(other) is CallSiteValue and other.target_name == "ndim":
            # ndarray.ndim is an integer data-model property. The value depends
            # on the runtime array, while the __index__ warrant does not.
            # (numpy/lib/tests/test_nanfunctions.py: (1,) * d.ndim)
            runtime_count_kind = "integer-warranted callsite ndim"
        elif type(other) is CallSiteValue and other.target_name == "nlanes":
            runtime_count_kind = "integer-warranted callsite nlanes"
        elif type(other) is CallSiteValue and other.target_name == "_AXIS_LEN":
            runtime_count_kind = "integer-warranted callsite _AXIS_LEN"
        elif (
            type(other) is CallSiteValue
            and other.target_name == "py.subscript"
            and len(other.arg_values) == 2
            and type(other.arg_values[0]) is CallSiteValue
            and other.arg_values[0].target_name == "shape"
        ):
            runtime_count_kind = "integer-warranted shape element"
        elif (
            type(other) is CallSiteValue
            and other.target_name == "max"
            and other.arg_values
            and all(
                _is_runtime_integer_expression(value)
                or (type(value) is TermValue and type(value.value) is int)
                for value in other.arg_values
            )
        ):
            # max preserves one of its operands.  A symbolic integer expression
            # remains unavailable until Python evaluates the function inputs,
            # while the ground integer peers preserve the __index__ warrant.
            runtime_count_kind = "integer-warranted callsite max"
        if runtime_count_kind is not None:
            from sugar_lift_py_tests.effect import (
                SequenceRepetitionRuntimeEffect,
                runtime_effect_evidence,
            )
            from sugar_lift_py_tests.outcome import Incomplete

            return Incomplete(
                SequenceRepetitionRuntimeEffect(
                    f"sequence repetition by {runtime_count_kind}: TupleValue depends "
                    f"on runtime __index__/length semantics; site={site}",
                    **runtime_effect_evidence("py.sequence_repeat", other, site),
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
        return self.py_subscript_coordinate(index, site)


def _is_runtime_integer_expression(value) -> bool:
    """Recognize the exact integer expression carried by NumPy's kron shape test."""
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import _Ctor

    if type(value) is not SymbolicValue or not isinstance(value.term, _Ctor):
        return False
    if value.term.name != "-" or len(value.term.args) != 2:
        return False
    return all(
        isinstance(arg, _Ctor) and arg.name == "call:len" and len(arg.args) == 1
        for arg in value.term.args
    )
