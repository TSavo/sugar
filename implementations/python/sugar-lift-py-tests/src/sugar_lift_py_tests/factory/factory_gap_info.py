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
    gap_kind: str = "Sugar"
    gap_locus: str = "AST"

    @property
    def message(self) -> str:
        return (
            f"write more {self.gap_kind} for this {self.gap_locus}: "
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
