from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SourceOracleEffect:
    reason: str

    @property
    def status(self) -> Literal["absent", "drifted"]:
        if (
            "source CID misaligned" in self.reason
            or "template CID misaligned" in self.reason
        ):
            return "drifted"
        return "absent"
