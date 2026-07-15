from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class OSExitRuntimeEffect(RuntimeEffect):
    """`os.exit(...)` halts the program at runtime. A named runtime effect: its identity
    is that it IS an OSExitRuntimeEffect, not a reason string. It is a RuntimeEffect, so
    it flows through the effect surface (require_effect, effect_reason, effect_status) as
    one."""

    def kind(self) -> type[RuntimeEffect]:
        return OSExitRuntimeEffect
