from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class DictUnpackRuntimeEffect(RuntimeEffect):
    """Keys and values supplied by a mapping that exists only at runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return DictUnpackRuntimeEffect
