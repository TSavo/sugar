from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class PowerRuntimeEffect(RuntimeEffect):
    """Power dispatch whose base value and ``__pow__`` exist only at runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return PowerRuntimeEffect
