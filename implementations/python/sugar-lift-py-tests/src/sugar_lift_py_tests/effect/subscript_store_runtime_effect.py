from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class SubscriptStoreRuntimeEffect(RuntimeEffect):
    """A subscript store whose post-state belongs to the Python runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return SubscriptStoreRuntimeEffect
