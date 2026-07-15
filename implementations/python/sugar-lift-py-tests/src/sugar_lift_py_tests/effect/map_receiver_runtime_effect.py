from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class MapReceiverRuntimeEffect(RuntimeEffect):
    """A map over a receiver whose collection semantics belong to the runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return MapReceiverRuntimeEffect
