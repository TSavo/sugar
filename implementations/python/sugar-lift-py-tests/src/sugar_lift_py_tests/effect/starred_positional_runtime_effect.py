from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class StarredPositionalRuntimeEffect(RuntimeEffect):
    """Call positional arity and bindings depend on a runtime iterable."""

    def kind(self) -> type[RuntimeEffect]:
        return StarredPositionalRuntimeEffect
