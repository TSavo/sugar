from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeEffect:
    """A runtime effect: a value that does not exist until the program runs. Abstract --
    never constructed directly. The KIND of runtime effect is a TYPE, so you build a
    named subclass (OSExitRuntimeEffect, ...); a generic RuntimeEffect does not exist."""

    reason: str

    def __post_init__(self) -> None:
        if type(self) is RuntimeEffect:
            raise TypeError(
                "RuntimeEffect is abstract and cannot be constructed directly; build a "
                "named runtime effect (e.g. OSExitRuntimeEffect). The kind of effect is "
                "a type, not a reason string."
            )
