from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class AttributeDeleteRuntimeEffect(RuntimeEffect):
    """Python runtime dispatch of ``del receiver.attribute``."""

    def kind(self) -> type[RuntimeEffect]:
        return AttributeDeleteRuntimeEffect
