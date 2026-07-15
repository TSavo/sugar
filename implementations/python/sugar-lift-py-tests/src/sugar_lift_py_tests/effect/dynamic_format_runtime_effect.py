from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class DynamicFormatRuntimeEffect(RuntimeEffect):
    """A formatted string requires runtime evaluation of its format shape."""

    def kind(self) -> type[RuntimeEffect]:
        return DynamicFormatRuntimeEffect
