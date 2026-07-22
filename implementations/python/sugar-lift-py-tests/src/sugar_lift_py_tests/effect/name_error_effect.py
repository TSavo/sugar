from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class NameErrorEffect(RuntimeEffect):
    """A Python read of an unbound name halts with a typed runtime NameError."""

    def kind(self) -> type[RuntimeEffect]:
        return NameErrorEffect
