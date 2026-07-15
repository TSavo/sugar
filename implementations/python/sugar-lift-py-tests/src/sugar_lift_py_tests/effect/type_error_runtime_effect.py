from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class TypeErrorRuntimeEffect(RuntimeEffect):
    """A ground cross-type operation Python defines no ordering for halts at
    runtime; the identity is the TYPE, not a reason string. It is a
    RuntimeEffect, so it flows through the effect surface (require_effect,
    effect_reason, effect_status) as one."""

    def kind(self) -> type[RuntimeEffect]:
        return TypeErrorRuntimeEffect
