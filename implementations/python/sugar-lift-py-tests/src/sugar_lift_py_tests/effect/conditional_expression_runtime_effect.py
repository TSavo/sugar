from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class ConditionalExpressionRuntimeEffect(RuntimeEffect):
    """A conditional expression whose selected arm depends on runtime state."""

    def kind(self) -> type[RuntimeEffect]:
        return ConditionalExpressionRuntimeEffect
