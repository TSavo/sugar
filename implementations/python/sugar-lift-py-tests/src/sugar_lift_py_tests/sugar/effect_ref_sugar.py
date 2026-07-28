"""Sugar for tree-native EffectRef / ObservationRef coordinates.

Coordinates are pure by default. When reduction context carries an
authenticated observed effect for the slot (handler routing deposited it),
the projection is that exact effect — never a reconstructed E().
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
        from sugar_lift_py_tests.floor.effect_coordinate import (
            EffectCoordinate,
            ObservedEffectValue,
        )

        # Observed-effect identity: the bound name projects the same RaiseEffect
        # the handler (or effect boundary) routed into this slot. No ambient
        # table — only the explicit context preimage deposited at the route.
        reader = getattr(ctx, "observed_effect_for", None) if ctx is not None else None
        effect = reader(self.slot_id) if reader is not None else None
        if effect is not None:
            return Complete(
                ObservedEffectValue(slot_id=self.slot_id, effect=effect, site=self.site)
            )
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
        from sugar_lift_py_tests.floor.effect_coordinate import (
            EffectCoordinate,
            ExceptionInfoCoordinate,
            ObservedExceptionInfoValue,
        )

        if self.projection == "exception_info":
            reader = getattr(ctx, "observed_effect_for", None)
            effect = reader(self.slot_id) if reader is not None else None
            if effect is not None:
                return Complete(
                    ObservedExceptionInfoValue(
                        slot_id=self.slot_id, effect=effect, site=self.site
                    )
                )
            return Complete(
                ExceptionInfoCoordinate(slot_id=self.slot_id, site=self.site)
            )
        if self.projection == "enter_result":
            from sugar_lift_py_tests.floor.manager_coordinate import (
                EnterResultCoordinate,
            )

            return Complete(EnterResultCoordinate(slot_id=self.slot_id, site=self.site))
        # warning_observation / effect: pure coordinate until binding facts exist
        return Complete(EffectCoordinate(slot_id=self.slot_id, site=self.site))
