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

    def attribute(self, name, site):
        # Bound methods and fields on a constructed list (``[].append``, ``xs.index``) stay the
        # py.getattr coordinate -- one law, shared with StringValue and the
        # other constructed containers. Never invent a method body or a field.
        del site
        from sugar_lift_py_tests.floor.getattr_coordinate import getattr_coordinate

        return getattr_coordinate(self, name, owner="ListValue.attribute")

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

    def contains(self, item, site):
        # A guarded needle is not one needle: distribute into its faces and
        # rejoin under the same guard before this receiver's own law runs.
        from sugar_lift_py_tests.floor.guarded_operand import (
            distribute_guarded_predicate,
        )

        distributed = distribute_guarded_predicate(self, item, "contains", site)
        if distributed is not None:
            return distributed
        # Membership over a constructed list: decide when every element has a
        # closed equality; emit a typed obligation when a member is symbolic;
        # stay loud for unconstructed member shapes (same law as SetValue).
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
                        "python.list.contains",
                        [
                            item.to_term(owner="python.list.contains member"),
                            self.to_term(owner="python.list.contains list"),
                        ],
                    ),
                    site,
                    operand_callsites=(*item.callsites(), *self.callsites()),
                )
            )
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="ListValue.contains",
            blame=str(site),
            observed=type(item).__name__,
            requested="constructed finite member or typed symbolic membership operand",
            fix="construct member equality on the Python floor or keep it loud",
        )

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
            # A constructed comprehension is already a sequence coordinate
            # (symbolic fold). Concatenate as another coordinate — never mint
            # RuntimeEffect over ComprehensionValue (that path required a
            # genuine runtime operand and rejected/faulted on py.listcomp
            # bodies carrying _Lambda before effect/runtime_effect admitted them).
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import Complete

            self_term = self.to_term(owner=str(site))
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
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.import_alias_value import ImportAliasValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) in (CallSiteValue, ImportAliasValue, SymbolicValue):
            return SymbolicValue(self.to_term(owner=str(site))).add(other, site)
        return super().add(other, site)

    def multiply(self, other, site):
        # Python list repetition, through the one sequence-repetition law.
        from sugar_lift_py_tests.floor.sequence_repetition import repeat_sequence

        return repeat_sequence(
            self, other, site, elements=self.elements, rebuild=ListValue
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
