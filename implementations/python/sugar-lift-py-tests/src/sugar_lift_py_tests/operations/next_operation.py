from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class NextOperation:
    method_name: ClassVar[str] = "next_with"
    owner: str = "BuiltinCallSugar"
    blame: str = "<unknown>"
