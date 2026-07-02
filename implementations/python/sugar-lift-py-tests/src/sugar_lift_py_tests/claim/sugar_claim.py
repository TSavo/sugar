from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .sugar_role import SugarRole


@dataclass(frozen=True)
class SugarClaim:
    name: str
    role: SugarRole
    owns: Callable[[object], bool]
    build: Callable[[object, object], object]
    comes_before: tuple[str, ...] = ()
