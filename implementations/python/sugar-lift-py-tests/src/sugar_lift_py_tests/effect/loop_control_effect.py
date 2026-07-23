from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LoopControlEffect:
    """A state-preserving loop-control halt owned by one loop coordinate."""

    action: Literal["break", "continue"]
    target_cid: str
    occurrence_cid: str

    def __post_init__(self) -> None:
        if self.action not in {"break", "continue"}:
            raise ValueError("unknown loop-control action")
        for field, value in (
            ("target_cid", self.target_cid),
            ("occurrence_cid", self.occurrence_cid),
        ):
            if not value.startswith("blake3-512:"):
                raise ValueError(f"{field} must be a CID")

    @property
    def reason(self) -> str:
        return f"{self.action} targeted at {self.target_cid}"
