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
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.term_value import TermValue

        # Materialize only concrete integer counts. Runtime parameters remain a
        # typed length effect, and builtin len(...) carries the integer/index
        # warrant needed to reach that same effect. Other opaque/import results
        # have not proved Python's __index__ contract and stay a construction gap.
        if type(other) is TermValue and type(other.value) is int:
            from sugar_lift_py_tests.outcome import Complete

            repeated = len(self.elements) * max(other.value, 0)
            from sugar_lift_py_tests.sugar.for_sugar import (
                STATIC_UNFOLD_LIMIT,
                finite_unfold_cap_panic,
            )

            if repeated > STATIC_UNFOLD_LIMIT:
                finite_unfold_cap_panic(
                    construction="ListValue repetition",
                    site=site,
                    observed=f"list repetition cardinality={repeated}",
                    limit=STATIC_UNFOLD_LIMIT,
                )
            return Complete(ListValue(self.elements * other.value))
        runtime_count_kind = None
        if type(other) is SymbolicValue:
            runtime_count_kind = "symbolic count"
        elif type(other) is OpaqueOpCallsite and other.callee == "len":
            runtime_count_kind = "integer-warranted len(...) result"
        elif type(other) is CallSiteValue and other.target_name == "ndim":
            runtime_count_kind = "integer-warranted callsite ndim"
        elif type(other) is CallSiteValue and other.target_name == "nlanes":
            # NumPy SIMD helper nlanes is the integer lane width of the active
            # vector type. Count depends on the runtime helper, not on lift.
            runtime_count_kind = "integer-warranted callsite nlanes"
        elif type(other) is CallSiteValue and other.target_name == "nlevels":
            # pandas Index.nlevels is an integer-valued data-model property.
            # Its value depends on the runtime index, but its __index__ warrant
            # does not.
            runtime_count_kind = "integer-warranted callsite nlevels"
        elif type(other) is CallSiteValue and other.target_name == "_AXIS_LEN":
            # pandas NDFrame._AXIS_LEN is the integer axis cardinality of the
            # box type (Series=1, DataFrame=2, ...). The constant is type-owned
            # but only available after the class coordinate is known at runtime.
            runtime_count_kind = "integer-warranted callsite _AXIS_LEN"
        elif (
            type(other) is CallSiteValue
            and other.target_name == "py.subscript"
            and len(other.arg_values) == 2
            and type(other.arg_values[0]) is CallSiteValue
            and other.arg_values[0].target_name == "shape"
        ):
            # obj.shape[i] is a non-negative integer dimension. The element is
            # unavailable until the concrete shape exists at runtime.
            runtime_count_kind = "integer-warranted shape element"
        elif (
            type(other) is CallSiteValue
            and other.target_name == "min"
            and len(other.arg_values) == 2
            and type(other.arg_values[0]) is CallSiteValue
            and other.arg_values[0].target_name == "abs"
            and len(other.arg_values[0].arg_values) == 1
            and type(other.arg_values[1]) is OpaqueOpCallsite
            and other.arg_values[1].callee == "len"
        ):
            # min(abs(periods), len(...)) is the pandas shift-count shape:
            # both arms are integer-valued, while the selected count remains
            # genuinely runtime-dependent.
            runtime_count_kind = "integer-warranted callsite min"
        elif (
            type(other) is CallSiteValue
            and other.target_name == "max"
            and other.arg_values
            and all(
                type(value) is SymbolicValue
                or (type(value) is TermValue and type(value.value) is int)
                for value in other.arg_values
            )
        ):
            # max preserves one of its operands. When every operand already
            # carries the runtime-integer/count shape, its result carries it too.
            runtime_count_kind = "integer-warranted callsite max"
        elif (
            type(other) is CallSiteValue
            and other.target_name == "numpy.sum"
            and len(other.arg_values) == 1
            and type(other.arg_values[0]) is CallSiteValue
            and other.arg_values[0].target_name == "isna"
        ):
            # numpy.sum over the Boolean result of Index.isna() is an integer
            # count.  The count depends on the runtime index contents, while
            # the exact qualified coordinate and Boolean producer warrant its
            # Python integer/index role.
            runtime_count_kind = "integer-warranted numpy.sum boolean count"
        elif _is_pyarrow_list_length_max_as_py(other):
            # Arrow list_value_length produces integer scalars, max preserves
            # that element type, and Scalar.as_py returns its Python integer.
            # The selected count itself still only exists when Arrow executes.
            runtime_count_kind = "pyarrow list-length maximum"
        if runtime_count_kind is not None:
            from sugar_lift_py_tests.effect import SequenceRepetitionRuntimeEffect
            from sugar_lift_py_tests.outcome import Incomplete

            return Incomplete(
                SequenceRepetitionRuntimeEffect(
                    f"sequence repetition by {runtime_count_kind}: ListValue depends "
                    f"on runtime __index__/length semantics; site={site}",
                    **runtime_effect_evidence("py.sequence_repeat", other, site),
                )
            )
        if (
            type(other) is CallSiteValue
            and other.target_name == "pandas._testing.box_expected"
            and len(other.arg_values) == 2
            and type(other.arg_values[0]) is CallSiteValue
            and other.arg_values[0].target_name == "numpy.array"
        ):
            # box_expected(array, box) selects an ndarray/Index/Series face.
            # Every face owns native elementwise multiplication; this is not
            # Python sequence repetition by an unproved count.
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                SymbolicValue(
                    ctor(
                        "*",
                        [
                            self.to_term(owner=str(site)),
                            other.to_term(owner=str(site)),
                        ],
                    )
                )
            )
        return super().multiply(other, site)

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


def _is_pyarrow_compute(value) -> bool:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.import_alias_value import ImportAliasValue

    return (
        type(value) is CallSiteValue
        and value.target_name == "compute"
        and value.body is None
        and len(value.arg_values) == 1
        and type(value.arg_values[0]) is ImportAliasValue
        and value.arg_values[0].name == "pyarrow"
    )


def _is_pyarrow_list_length_max_as_py(value) -> bool:
    """Recognize the source-proved pandas Arrow list-length maximum."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    if (
        type(value) is not CallSiteValue
        or value.target_name != "as_py"
        or value.body is not None
        or len(value.arg_values) != 1
    ):
        return False
    maximum = value.arg_values[0]
    if (
        type(maximum) is not CallSiteValue
        or maximum.target_name != "max"
        or maximum.body is not None
        or len(maximum.arg_values) != 2
        or not _is_pyarrow_compute(maximum.arg_values[0])
    ):
        return False
    lengths = maximum.arg_values[1]
    return (
        type(lengths) is CallSiteValue
        and lengths.target_name == "list_value_length"
        and lengths.body is None
        and len(lengths.arg_values) == 2
        and _is_pyarrow_compute(lengths.arg_values[0])
    )
