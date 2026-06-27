from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PanicKind = Literal["sugar", "floor", "unexpected"]


@dataclass(frozen=True)
class PanicRecord:
    target: str
    kind: PanicKind
    owner: str
    blame: str
    observed: str
    requested: str
    fix: str
    message: str

    def to_json(self) -> dict[str, str]:
        return {
            "target": self.target,
            "kind": self.kind,
            "owner": self.owner,
            "blame": self.blame,
            "observed": self.observed,
            "requested": self.requested,
            "fix": self.fix,
            "message": self.message,
        }
