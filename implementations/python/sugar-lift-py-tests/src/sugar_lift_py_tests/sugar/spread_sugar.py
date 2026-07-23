from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class SpreadSugar(Sugar):
    value: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # Witnessed through the enclosing call/display, where Starred has a role.
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.spread_value import SpreadValue
        from sugar_lift_py_tests.outcome import Complete

        return self.value.desugar(ctx).and_then(
            lambda value: Complete(SpreadValue(value))
        )
