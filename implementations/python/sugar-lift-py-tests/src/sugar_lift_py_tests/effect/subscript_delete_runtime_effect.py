from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class SubscriptDeleteRuntimeEffect(RuntimeEffect):
    """Python runtime dispatch of ``del receiver[index]``."""

    def kind(self) -> type[RuntimeEffect]:
        return SubscriptDeleteRuntimeEffect
