from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class AttributeStoreRuntimeEffect(RuntimeEffect):
    """An attribute store whose receiver identity belongs to the runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return AttributeStoreRuntimeEffect
