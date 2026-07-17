from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class AppendRuntimeEffect(RuntimeEffect):
    """An append whose receiver and mutated post-state belong to Python runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return AppendRuntimeEffect
