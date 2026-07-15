from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class DivisionByZeroRuntimeEffect(RuntimeEffect):
    """Division by a concrete zero halts the program at runtime; the identity is the
    TYPE, not a reason string. It is a RuntimeEffect, so it flows through the effect
    surface (require_effect, effect_reason, effect_status) as one."""

    def kind(self) -> type[RuntimeEffect]:
        return DivisionByZeroRuntimeEffect
