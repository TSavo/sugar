from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class FollowStep:
    """One heap-resident decision about an enclosing block's remaining work."""

    continues: bool
    keeps_rest: bool = False
    transform: Callable[[tuple], tuple] | None = None
    continuation_guard: object | None = None

    @classmethod
    def continue_with(
        cls,
        transform: Callable[[tuple], tuple] | None = None,
        *,
        continuation_guard: object | None = None,
    ) -> "FollowStep":
        return cls(
            continues=True,
            transform=transform,
            continuation_guard=continuation_guard,
        )

    @classmethod
    def halt(cls, *, keeps_rest: bool) -> "FollowStep":
        return cls(continues=False, keeps_rest=keeps_rest)
