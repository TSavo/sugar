from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class SetMethodRuntimeEffect(RuntimeEffect):
    """A set builtin method whose mutation and iteration-order semantics belong to the runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return SetMethodRuntimeEffect
