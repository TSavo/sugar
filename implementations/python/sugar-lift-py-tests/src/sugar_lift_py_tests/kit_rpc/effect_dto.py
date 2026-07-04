from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.effect import (
    Effect,
    effect_reason,
    effect_status,
    require_effect,
)

from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto


@dataclass(frozen=True)
class EffectDto:
    name: str
    effect: Effect
    source_memento: SourceMementoDto | dict[str, Any]

    def to_rpc(self) -> dict[str, Any]:
        effect = require_effect(self.effect)
        return {
            "kind": "effect",
            "name": self.name,
            "status": effect_status(effect),
            "reason": effect_reason(effect),
            "sourceMemento": to_rpc_value(self.source_memento),
        }
