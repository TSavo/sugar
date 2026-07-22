from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class AttributeDeleteRuntimeEffect(RuntimeEffect):
    """An attribute deletion whose descriptor dispatch belongs to Python."""

    def kind(self) -> type[RuntimeEffect]:
        return AttributeDeleteRuntimeEffect
