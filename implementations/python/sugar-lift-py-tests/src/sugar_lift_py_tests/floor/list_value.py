from __future__ import annotations

from dataclasses import dataclass

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

    def multiply(self, other, site):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.import_alias_value import ImportAliasValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.term_value import TermValue

        if type(other) is TermValue and type(other.value) is int:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(ListValue(self.elements * other.value))
        if type(other) in (CallSiteValue, ImportAliasValue, SymbolicValue):
            return SymbolicValue(self.to_term(owner=str(site))).multiply(other, site)
        return super().multiply(other, site)

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
            from sugar_lift_py_tests.effect import IndexErrorRuntimeEffect

            return Incomplete(
                IndexErrorRuntimeEffect(
                    f"list index out of range runtime boundary: "
                    f"index={i} length={n}; owner=ListValue.subscript site={site}"
                )
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
            from sugar_lift_py_tests.effect import IndexErrorRuntimeEffect

            return Incomplete(
                IndexErrorRuntimeEffect(
                    "list assignment index out of range runtime boundary: "
                    f"index={i} length={n}; owner=ListValue.setitem site={site}"
                )
            )
        from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect

        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "list subscript store requires a concrete integer index; "
                f"owner=ListValue.setitem site={site}"
            )
        )

    def delitem(self, index, site):
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

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
            from sugar_lift_py_tests.effect import IndexErrorRuntimeEffect

            return Incomplete(
                IndexErrorRuntimeEffect(
                    "list deletion index out of range runtime boundary: "
                    f"index={i} length={n}; owner=ListValue.delitem site={site}"
                )
            )
        from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect

        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "list subscript delete requires a concrete integer index; "
                f"owner=ListValue.delitem site={site}"
            )
        )
