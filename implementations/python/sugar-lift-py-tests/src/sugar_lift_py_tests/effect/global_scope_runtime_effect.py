from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class GlobalScopeRuntimeEffect(RuntimeEffect):
    """A declaration whose writes resolve through a runtime module frame."""
