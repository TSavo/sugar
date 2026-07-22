"""Floor projection of a tree-native effect coordinate.

Syntax creates EffectRef(slot). Routing authenticates the slot during desugar
of the matching try/with arm. This value **seals** that testimony at desugar
time (open → authenticated payload) so later post/inv projection does not
depend on ambient auth tables after the reduction wave ends.

Never a constructed E().
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import Effect
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.effect.warning_effect import WarningEffect

from .floor_value import FloorValue


@dataclass(frozen=True)
class EffectCoordinate(FloorValue):
    """Coordinate from syntax; ``effect`` is sealed when routing authenticated it."""

    slot_id: str
    effect: Effect | None = None
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        if self.effect is None:
            return ctor("python:effect_slot", [str_const(self.slot_id)])
        if isinstance(self.effect, RaiseEffect):
            name = self.effect.exception_name or "unknown"
            return ctor(
                "python:observed_exception",
                [str_const(name), str_const(self.slot_id)],
            )
        if isinstance(self.effect, WarningEffect):
            return ctor(
                "python:observed_warning",
                [str_const(self.effect.category_name), str_const(self.slot_id)],
            )
        return ctor(
            "python:observed_effect",
            [str_const(type(self.effect).__name__), str_const(self.slot_id)],
        )


@dataclass(frozen=True)
class ExceptionInfoCoordinate(FloorValue):
    """Observation wrapper: ``.value`` projects the same sealed effect slot."""

    slot_id: str
    effect: Effect | None = None
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exception_info", [str_const(self.slot_id)])

    def attribute(self, name, site):
        if name == "value":
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                EffectCoordinate(
                    slot_id=self.slot_id, effect=self.effect, site=site
                )
            )
        return super().attribute(name, site)
