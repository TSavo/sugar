from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class BytesConversionRuntimeEffect(RuntimeEffect):
    """A __bytes__ conversion Python does not define statically for this operand."""

    def kind(self) -> type[RuntimeEffect]:
        return BytesConversionRuntimeEffect
