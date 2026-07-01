from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NextOperation:
    owner: str = "BuiltinCallSugar"
    blame: str = "<unknown>"
