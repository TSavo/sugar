from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class StringFloatConversionRuntimeEffect(RuntimeEffect):
    """A string-to-float conversion whose parse outcome belongs to the runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return StringFloatConversionRuntimeEffect
