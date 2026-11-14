from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class LoopControlEffect:
    """A state-preserving loop-control halt owned by one loop coordinate."""

    action: Literal["break", "continue"]
    target_cid: str
    occurrence_cid: str
    # The source fragment of the ``break``/``continue`` statement the halt
    # left at (#7766): the address its panic locus states.  Testimony about
    # the halt, not what it denotes (``occurrence_cid`` is its identity), so
    # it never enters equality or repr.
    site: object | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.action not in {"break", "continue"}:
            raise ValueError("unknown loop-control action")
        for name, value in (
            ("target_cid", self.target_cid),
            ("occurrence_cid", self.occurrence_cid),
        ):
            if not value.startswith("blake3-512:"):
                raise ValueError(f"{name} must be a CID")

    @property
    def reason(self) -> str:
        return f"{self.action} targeted at {self.target_cid}"
