from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DigRefusal:
    """A tower the digger declined to climb, recorded instead of hidden."""

    callee: str
    blame: str
    caught: str
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "dig-refusal",
            "callee": self.callee,
            "blame": self.blame,
            "caught": self.caught,
            "reason": self.reason,
        }

    def to_rpc(self) -> dict[str, Any]:
        return self.to_json()
