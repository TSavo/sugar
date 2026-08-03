from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_body
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class ModuleBlockSugar(Sugar):
    """The already-constructed statements of one source module, in order."""

    statements: tuple[Sugar, ...]
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="BlockValue",
            reason="module blocks project the ordinary constructed block",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return reduce_body(self.statements, ctx)
