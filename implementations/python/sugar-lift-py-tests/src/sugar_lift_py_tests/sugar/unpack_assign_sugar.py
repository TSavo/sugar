from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class UnpackAssignSugar(Sugar):
    rhs: Sugar
    slot: object
    pattern: object
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.unpack_value_binding import UnpackValueBinding

        return self.rhs.desugar(ctx).and_then(self._resolved_binding)

    def _resolved_binding(self, rhs_value):
        from sugar_lift_py_tests.floor.unpack_value_binding import UnpackValueBinding

        if not self._matches(self.pattern, rhs_value):
            from sugar_lift_py_tests.gap.info import GapKind, GapLocus
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="UnpackAssignSugar",
                blame=str(self.site),
                observed=(
                    "unpack RHS has no exact structural testimony for "
                    f"{type(rhs_value).__name__}"
                ),
                requested="a resolved tuple/list value matching the typed pattern",
                fix=(
                    "keep unconstrained unpacking loud until its iterable and "
                    "arity outcome can be represented without fabricated success"
                ),
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        return Complete(
            UnpackValueBinding(self.slot, rhs_value, self.pattern, self.site)
        )

    @classmethod
    def _matches(cls, pattern, value):
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_source_tree.unpack_assignment import UnpackNamePattern

        if isinstance(pattern, UnpackNamePattern):
            return True
        if not isinstance(value, (TupleValue, ListValue)):
            return False
        if len(pattern.elements) != len(value.elements):
            return False
        return all(
            cls._matches(child_pattern, child_value)
            for child_pattern, child_value in zip(pattern.elements, value.elements)
        )
