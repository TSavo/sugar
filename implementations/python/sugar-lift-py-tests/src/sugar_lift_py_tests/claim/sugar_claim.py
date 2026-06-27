from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .sugar_role import SugarRole


@dataclass(frozen=True)
class SugarClaim:
    name: str
    role: SugarRole
    owns: Callable[[Any], bool]
    build: Callable[[Any], Any]
