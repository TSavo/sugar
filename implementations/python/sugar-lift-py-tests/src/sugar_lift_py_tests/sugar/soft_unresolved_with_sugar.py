"""Soft unresolved With for authenticated dual-mode factory frame projection.

Only installed when ``TreeConstructionContextV1.frame_projection`` is true.
The CM return path of factories like ``pytest.raises`` never desugars this
arm; the function-form branch may contain nested Withs that lack a closed
contract row during frame projection. Soft incompletes keep that branch from
aborting the factory's source-visible call frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class SoftUnresolvedWithSugar(Sugar):
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ExitSet",
            reason="frame-projection soft incomplete for dual-mode factory branches",
        )

    def desugar(self, ctx=None) -> Outcome:
        from sugar_lift_py_tests.effect import CoverageGapEffect

        return Incomplete(
            CoverageGapEffect(
                boundary="dual-mode-factory-with",
                reason="dual-mode factory function-form With left unresolved "
                "during authenticated call-frame projection",
            )
        )
