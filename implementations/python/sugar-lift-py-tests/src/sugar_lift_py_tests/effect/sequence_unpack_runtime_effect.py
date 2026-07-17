from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class SequenceUnpackRuntimeEffect(RuntimeEffect):
    """Assignment unpack whose cardinality is known only at runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return SequenceUnpackRuntimeEffect
