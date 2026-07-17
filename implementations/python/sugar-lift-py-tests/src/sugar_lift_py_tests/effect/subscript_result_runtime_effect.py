from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class SubscriptResultRuntimeEffect(RuntimeEffect):
    """A subscript whose receiver's runtime container shape is not known."""

    def kind(self) -> type[RuntimeEffect]:
        return SubscriptResultRuntimeEffect
