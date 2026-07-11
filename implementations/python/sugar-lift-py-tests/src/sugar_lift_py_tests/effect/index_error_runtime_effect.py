from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class IndexErrorRuntimeEffect(RuntimeEffect):
    """Subscript with a concrete out-of-range index halts the program at runtime;
    the identity is the TYPE, not a reason string. It is a RuntimeEffect, so it
    flows through the effect surface as one."""
