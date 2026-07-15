from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class AsyncIterationRuntimeEffect(RuntimeEffect):
    """An async iteration that only a runtime async-iterator can drive."""

    def kind(self) -> type[RuntimeEffect]:
        return AsyncIterationRuntimeEffect
