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
    halt_guard: object | None = None
    """A complementary SECOND face for a step that neither purely continues nor
    purely halts.

    ``continues=True`` with ``halt_guard=g`` means: this step halts under ``g``
    with the step's own effect and the PREFIX state, and continues under
    ``not g``.  Both faces survive; neither is chosen at lift time.

    This is what a store needs.  ``continues=True, halt_guard=None`` (the
    default) is the old unconditional-continue behaviour and is what every
    non-store step still returns."""

    @classmethod
    def continue_with(
        cls,
        transform: Callable[[tuple], tuple] | None = None,
        *,
        continuation_guard: object | None = None,
        halt_guard: object | None = None,
    ) -> "FollowStep":
        return cls(
            continues=True,
            transform=transform,
            continuation_guard=continuation_guard,
            halt_guard=halt_guard,
        )

    @classmethod
    def halt(cls, *, keeps_rest: bool) -> "FollowStep":
        return cls(continues=False, keeps_rest=keeps_rest)
