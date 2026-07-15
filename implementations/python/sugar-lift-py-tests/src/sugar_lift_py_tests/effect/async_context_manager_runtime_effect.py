from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class AsyncContextManagerRuntimeEffect(RuntimeEffect):
    """An async context entry that only a runtime async manager can perform."""

    def kind(self) -> type[RuntimeEffect]:
        return AsyncContextManagerRuntimeEffect
