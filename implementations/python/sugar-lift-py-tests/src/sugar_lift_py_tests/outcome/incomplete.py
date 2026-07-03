from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import Effect, effect_reason, require_effect


@dataclass(frozen=True)
class Incomplete:
    effect: Effect

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect", require_effect(self.effect))

    @property
    def reason(self) -> str:
        return effect_reason(self.effect)
