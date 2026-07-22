"""Sugar for tree-native EffectRef / ObservationRef coordinates."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class EffectRefSugar(Sugar):
    """Meaning of EffectRef(slot): a coordinate, open until routing authenticates."""

    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        # Coordinate sugars are testified by try/with twins, not a free pair.
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.effect_auth import lookup_slot
        from sugar_lift_py_tests.floor.effect_coordinate import EffectCoordinate

        # Seal route-time testimony now — post/inv may run after the auth wave.
        return Complete(
            EffectCoordinate(
                slot_id=self.slot_id,
                effect=lookup_slot(self.slot_id),
                site=self.site,
            )
        )


@dataclass(frozen=True)
class ObservationRefSugar(Sugar):
    """Meaning of ObservationRef(slot, projection): contract-declared observation."""

    slot_id: str
    projection: str  # "exception_info" | "warning_observation" | "effect"
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.effect_auth import lookup_slot
        from sugar_lift_py_tests.effect.warning_effect import WarningEffect
        from sugar_lift_py_tests.floor.effect_coordinate import (
            EffectCoordinate,
            ExceptionInfoCoordinate,
        )
        from sugar_lift_py_tests.floor.warning_observation_value import (
            WarningObservationValue,
        )

        effect = lookup_slot(self.slot_id)
        if self.projection == "exception_info":
            return Complete(
                ExceptionInfoCoordinate(
                    slot_id=self.slot_id, effect=effect, site=self.site
                )
            )
        if self.projection == "warning_observation":
            if isinstance(effect, WarningEffect):
                return Complete(WarningObservationValue(effect=effect))
            return Complete(
                EffectCoordinate(
                    slot_id=self.slot_id, effect=effect, site=self.site
                )
            )
        return Complete(
            EffectCoordinate(
                slot_id=self.slot_id, effect=effect, site=self.site
            )
        )
