from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class DictMethodRuntimeEffect(RuntimeEffect):
    """A dict builtin method whose view/mutation semantics belong to the runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return DictMethodRuntimeEffect
