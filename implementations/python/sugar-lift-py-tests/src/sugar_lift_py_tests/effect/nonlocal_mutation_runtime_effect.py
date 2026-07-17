from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class NonlocalMutationRuntimeEffect(RuntimeEffect):
    """Mutation routed through an enclosing runtime function frame."""

    def kind(self) -> type[RuntimeEffect]:
        return NonlocalMutationRuntimeEffect
