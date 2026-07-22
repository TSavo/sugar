from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class SubscriptDeleteRuntimeEffect(RuntimeEffect):
    """A subscript deletion whose __delitem__ dispatch belongs to Python."""

    def kind(self) -> type[RuntimeEffect]:
        return SubscriptDeleteRuntimeEffect
