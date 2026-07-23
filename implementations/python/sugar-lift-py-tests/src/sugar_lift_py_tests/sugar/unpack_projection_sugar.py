from __future__ import annotations

from dataclasses import dataclass, field

from sugar_source_tree.unpack_assignment import Position

from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class UnpackProjectionSugar(Sugar):
    slot: object
    path: tuple[Position, ...]
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def __post_init__(self):
        if not self.path or any(not isinstance(step, Position) for step in self.path):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap
            from sugar_lift_py_tests.gap.info import GapKind, GapLocus

            construction_panic_gap(
                owner="UnpackProjectionSugar",
                blame=str(self.site),
                observed=f"invalid typed unpack path {self.path!r}",
                requested="a non-empty path of Position steps",
                fix="construct projections only from the authenticated target pattern",
                gap_kind=GapKind.CONSTRUCTOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )

    def desugar(self, ctx=None):
        del ctx
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.unpack_value_binding import unpack_slot_term
        from sugar_lift_py_tests.ir import ctor, num

        path = ctor(
            "python:unpack_path",
            [ctor("python:position", [num(step.index)]) for step in self.path],
        )
        return Complete(
            SymbolicValue(
                ctor(
                    "python:unpack_projection",
                    [unpack_slot_term(self.slot), path],
                )
            )
        )
