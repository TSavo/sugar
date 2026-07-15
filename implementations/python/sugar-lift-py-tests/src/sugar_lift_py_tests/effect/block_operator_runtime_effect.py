from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class BlockOperatorRuntimeEffect(RuntimeEffect):
    """An operator over a multi-exit or fall-through block that only runtime control flow can host."""

    def kind(self) -> type[RuntimeEffect]:
        return BlockOperatorRuntimeEffect
