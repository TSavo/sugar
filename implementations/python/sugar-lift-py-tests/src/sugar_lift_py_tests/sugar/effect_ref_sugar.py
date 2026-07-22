"""Sugar for tree-native EffectRef / ObservationRef coordinates.

Always desugars to a pure coordinate. No ambient lookup. No sealing.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class EffectRefSugar(Sugar):
    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.effect_coordinate import EffectCoordinate

        return Complete(EffectCoordinate(slot_id=self.slot_id, site=self.site))


@dataclass(frozen=True)
class ObservationRefSugar(Sugar):
    slot_id: str
    projection: str
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.effect_coordinate import (
            EffectCoordinate,
            ExceptionInfoCoordinate,
        )

        if self.projection == "exception_info":
            return Complete(
                ExceptionInfoCoordinate(slot_id=self.slot_id, site=self.site)
            )
        if self.projection == "enter_result":
            from sugar_lift_py_tests.floor.manager_coordinate import (
                EnterResultCoordinate,
            )

            return Complete(
                EnterResultCoordinate(slot_id=self.slot_id, site=self.site)
            )
        # warning_observation / effect: pure coordinate until binding facts exist
        return Complete(EffectCoordinate(slot_id=self.slot_id, site=self.site))
