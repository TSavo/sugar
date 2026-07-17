from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class ContextManagerExitRuntimeEffect(RuntimeEffect):
    """A runtime-selected manager decides whether exceptional exit suppresses."""

    def kind(self) -> type[RuntimeEffect]:
        return ContextManagerExitRuntimeEffect
