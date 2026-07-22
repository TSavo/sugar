"""Floor projection of a tree-native effect coordinate.

``EffectRef(S)`` always desugars to ``effect-slot(S)`` — a pure coordinate.
Authentication is **not** stored here. The router emits EffectBinding facts
into the same record (effect_slot_kind / type / identity). Missing binding
is an open obligation elsewhere, never a quietly usable observed-exception term.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from .floor_value import FloorValue


@dataclass(frozen=True)
class EffectCoordinate(FloorValue):
    """Coordinate only. Always projects ``python:effect_slot(slot_id)``."""

    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:effect_slot", [str_const(self.slot_id)])


@dataclass(frozen=True)
class ExceptionInfoCoordinate(FloorValue):
    """Observation wrapper: ``.value`` is the same pure effect coordinate."""

    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exception_info", [str_const(self.slot_id)])

    def attribute(self, name, site):
        if name == "value":
            from sugar_lift_py_tests.outcome import Complete

            return Complete(EffectCoordinate(slot_id=self.slot_id, site=site))
        return super().attribute(name, site)
