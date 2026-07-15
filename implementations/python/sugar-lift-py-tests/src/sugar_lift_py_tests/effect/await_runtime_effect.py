from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class AwaitRuntimeEffect(RuntimeEffect):
    """An await whose awaitable can only be forced by the runtime event loop."""

    def kind(self) -> type[RuntimeEffect]:
        return AwaitRuntimeEffect
