from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class ContextManagerUnpackRuntimeEffect(RuntimeEffect):
    """A context manager's entered value needs runtime unpacking."""

    def kind(self) -> type[RuntimeEffect]:
        return ContextManagerUnpackRuntimeEffect
