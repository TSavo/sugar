from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class ContextManagerEnterRuntimeEffect(RuntimeEffect):
    """A runtime-selected manager decides whether ``__enter__`` completes."""

    def kind(self) -> type[RuntimeEffect]:
        return ContextManagerEnterRuntimeEffect
