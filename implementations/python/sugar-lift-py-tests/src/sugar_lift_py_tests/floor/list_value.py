from __future__ import annotations

from dataclasses import dataclass
from sugar_lift_py_tests.effect import runtime_effect_evidence

from .floor_value import FloorValue


@dataclass(frozen=True)
class ListValue(FloorValue):
    """A list of reduced floor values.

    Order matters for a list -- the tuple already preserves it. The sugar reduces
    each element; the floor holds what those reductions were. No methods beyond
    the dataclass -- floors this list does not implement panic for free via
    FloorValue defaults.
    """

    elements: tuple

    def to_term(self, *, owner: str):
        # Project elements into FOL — assert equality / dig return faces.
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "array",
            [elt.to_term(owner=owner) for elt in self.elements],
        )

    def truth(self, site):
        # A list's truth is nonempty.
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
        # A list knows its length: the count of reduced elements.
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(len(self.elements)))

    def append_with(self, value, site):
        # Concrete history folds: the updated list is the old elements plus the
        # new value. Symbolic receivers stay on the default panic.
        del site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(ListValue((*self.elements, value)))

    def add(self, other, site):
        """Python list concatenation, or a cited coordinate for an opaque peer."""
        if type(other) is ListValue:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(ListValue((*self.elements, *other.elements)))
        from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue

        if type(other) is ComprehensionValue:
            from sugar_lift_py_tests.effect import (
                SequenceConcatenationRuntimeEffect,
                is_lift_time_decidable,
                runtime_effect_evidence,
            )
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            self_term = self.to_term(owner=str(site))
            if is_lift_time_decidable(self_term) and is_lift_time_decidable(other.term):
                return Complete(
                    ComprehensionValue(
                        ctor(
                            "+",
                            [
                                self_term,
                                other.term,
                            ],
                        )
                    )
                )
            return Incomplete(
                SequenceConcatenationRuntimeEffect(
                    "list concatenation depends on runtime comprehension members; "
                    f"owner=ListValue.add site={site}",
                    **runtime_effect_evidence("py.sequence_concat", other, site),
                )
            )
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.import_alias_value import ImportAliasValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) in (CallSiteValue, ImportAliasValue, SymbolicValue):
            return SymbolicValue(self.to_term(owner=str(site))).add(other, site)
        return super().add(other, site)

    def multiply(self, other, site):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.term_value import TermValue

        if type(other) is TermValue and type(other.value) is int:
            from sugar_lift_py_tests.outcome import Complete

            repeated = len(self.elements) * max(other.value, 0)
            static_unfold_limit = 128

            if repeated > static_unfold_limit:
                from sugar_lift_py_tests.gap.panic import construction_panic_gap

                construction_panic_gap(
                    owner="ListValue.multiply",
                    blame=str(site),
                    observed=f"list repetition cardinality={repeated}",
                    requested=f"finite repetition at or below {static_unfold_limit}",
                    fix="keep exact sequence repetition within the finite unfold budget",
                )
            return Complete(ListValue(self.elements * other.value))
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            SymbolicValue(
                ctor(
                    "python:mul",
                    [
                        self.to_term(owner=str(site)),
                        other.to_term(owner=str(site)),
                    ],
                )
            )
        )

    def matrix_multiply(self, other, site):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if type(other) is CallSiteValue and other.body is None:
            from sugar_lift_py_tests.effect import runtime_matrix_multiply

            return runtime_matrix_multiply(self, other, site)
        return super().matrix_multiply(other, site)

    def subscript(self, index, site):
        # Concrete list + in-range TermValue int folds to the element; out of
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
                owner="ListValue.subscript",
                operation="list subscript",
                index=i,
                length=n,
                site=site,
            )
        return self.py_subscript_coordinate(index, site)

    def setitem(self, index, value, site):
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        if type(index) is TermValue and type(index.value) is int:
            i = index.value
            n = len(self.elements)
            if -n <= i < n:
                resolved = i if i >= 0 else n + i
                updated = (
                    *self.elements[:resolved],
                    value,
                    *self.elements[resolved + 1 :],
                )
                return Complete(ListValue(updated))
            from sugar_lift_py_tests.floor.ground_index_error import (
                ground_index_error,
            )

            return ground_index_error(
                owner="ListValue.setitem",
                operation="list assignment",
                index=i,
                length=n,
                site=site,
            )
        from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect

        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "list subscript store requires a concrete integer index; "
                f"owner=ListValue.setitem site={site}",
                **runtime_effect_evidence("py.setitem", index, site),
            )
        )

    def delitem(self, index, site):
        from sugar_lift_py_tests.floor.slice_value import SliceValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        if isinstance(index, SliceValue):
            bounds = (index.lower, index.upper, index.step)
            if all(
                bound is None or (type(bound) is TermValue and type(bound.value) is int)
                for bound in bounds
            ):
                lower, upper, step = (
                    bound.value if isinstance(bound, TermValue) else None
                    for bound in bounds
                )
                selected = set(range(len(self.elements))[slice(lower, upper, step)])
                return Complete(
                    ListValue(
                        tuple(
                            value
                            for position, value in enumerate(self.elements)
                            if position not in selected
                        )
                    )
                )
            from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect

            return Incomplete(
                SubscriptStoreRuntimeEffect(
                    "list slice deletion depends on runtime slice bounds; "
                    f"owner=ListValue.delitem site={site}",
                    **runtime_effect_evidence("py.delitem", index, site),
                )
            )

        if type(index) is TermValue and type(index.value) is int:
            i = index.value
            n = len(self.elements)
            if -n <= i < n:
                resolved = i if i >= 0 else n + i
                return Complete(
                    ListValue(
                        (*self.elements[:resolved], *self.elements[resolved + 1 :])
                    )
                )
            from sugar_lift_py_tests.floor.ground_index_error import (
                ground_index_error,
            )

            return ground_index_error(
                owner="ListValue.delitem",
                operation="list deletion",
                index=i,
                length=n,
                site=site,
            )
        from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect

        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "list subscript delete requires a concrete integer index; "
                f"owner=ListValue.delitem site={site}",
                **runtime_effect_evidence("py.delitem", index, site),
            )
        )
