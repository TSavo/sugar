from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class FactoryGapInfo:
    owner: str
    blame: str
    observed: str
    requested: str
    fix: str

    @property
    def message(self) -> str:
        return (
            "write more Sugar for this AST: "
            f"owner={self.owner} blame={self.blame} observed={self.observed} "
            f"requested={self.requested} fix={self.fix}"
        )

    def to_json(self) -> Dict[str, str]:
        return {
            "owner": self.owner,
            "blame": self.blame,
            "observed": self.observed,
            "requested": self.requested,
            "fix": self.fix,
        }
