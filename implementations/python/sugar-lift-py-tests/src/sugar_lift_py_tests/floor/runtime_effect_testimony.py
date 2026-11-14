from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import Effect, require_effect

from .floor_value import FloorValue


@dataclass(frozen=True)
class RuntimeEffectTestimony(FloorValue):
    """Red testimony that a runtime-selected step COMPLETED on this face.

    A store (``o.x = v``, ``o[k] = v``, ``del o.x``) is decided by the runtime:
    it completes under one guard and halts under the other.  The halted face is
    a ``Halted`` arm.  The completed face still records which effect the
    runtime answered, so the record says the store happened rather than
    nothing happening.  That record entry is this type.

    It is not a halt and never stands for one: a completed record holds no
    halt (#7826).  It states no inv, posts no exit, mints no row and projects
    no call edge; the rest of the block goes on after it.
    """

    effect: Effect

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect", require_effect(self.effect))

    def guarded(self, formula):
        # The testimony rides under its arm's guard; guarding a fact about the
        # runtime's answer changes nothing it states.
        del formula
        return self
