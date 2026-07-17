from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class AttributeAugAssignRuntimeEffect(RuntimeEffect):
    """An in-place attribute update whose receiver is selected at runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return AttributeAugAssignRuntimeEffect
