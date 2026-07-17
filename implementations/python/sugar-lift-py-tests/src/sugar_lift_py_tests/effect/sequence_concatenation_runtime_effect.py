from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class SequenceConcatenationRuntimeEffect(RuntimeEffect):
    """Sequence concatenation whose members depend on runtime iteration."""

    def kind(self) -> type[RuntimeEffect]:
        return SequenceConcatenationRuntimeEffect
