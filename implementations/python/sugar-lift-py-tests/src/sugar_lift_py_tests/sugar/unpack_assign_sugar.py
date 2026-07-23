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

        return self.rhs.desugar(ctx).and_then(
            lambda rhs_value: Complete(
                UnpackValueBinding(self.slot, rhs_value, self.pattern, self.site)
            )
        )
