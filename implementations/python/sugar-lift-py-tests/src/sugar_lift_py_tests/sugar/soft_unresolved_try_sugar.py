"""Soft unresolved Try for authenticated dual-mode factory frame projection.

Only installed when ``TreeConstructionContextV1.frame_projection`` is true and
a handler type is not a bare Name (e.g. ``except re.error``). Full reduction of
that arm still stays incomplete; a manager-return path must not abort
class/base projection on a dormant except arm.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class SoftUnresolvedTrySugar(Sugar):
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ExitSet",
            reason="frame-projection soft incomplete for non-Name except types",
        )

    def desugar(self, ctx=None) -> Outcome:
        from sugar_lift_py_tests.effect import CoverageGapEffect

        return Incomplete(
            CoverageGapEffect(
                boundary="dual-mode-factory-try",
                reason="non-Name except type left unresolved during authenticated "
                "call-frame projection",
            )
        )
