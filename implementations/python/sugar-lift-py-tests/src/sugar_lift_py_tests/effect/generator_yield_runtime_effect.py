from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class GeneratorYieldRuntimeEffect(RuntimeEffect):
    """A generator suspension whose resume value belongs to Python runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return GeneratorYieldRuntimeEffect
