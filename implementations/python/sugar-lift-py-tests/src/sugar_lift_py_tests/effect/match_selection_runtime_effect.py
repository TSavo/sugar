from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class MatchSelectionRuntimeEffect(RuntimeEffect):
    """A match statement whose selected case depends on a runtime value."""

    def kind(self) -> type[RuntimeEffect]:
        return MatchSelectionRuntimeEffect
