from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class ConstructorRuntimeEffect(RuntimeEffect):
    """A class construction whose Python initialization must execute at runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return ConstructorRuntimeEffect
