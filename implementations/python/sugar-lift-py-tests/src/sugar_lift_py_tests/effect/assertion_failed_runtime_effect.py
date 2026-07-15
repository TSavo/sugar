from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class AssertionFailedRuntimeEffect(RuntimeEffect):
    """A ground-False assert halts the program at runtime (AssertionError). A named
    runtime effect: the identity is that it IS an AssertionFailedRuntimeEffect, not a
    reason string. Per the gap/fact discriminator this is a recognized FACT the
    program halts -- never a lift-side panic; nothing is missing."""

    def kind(self) -> type[RuntimeEffect]:
        return AssertionFailedRuntimeEffect
