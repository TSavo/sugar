from __future__ import annotations

from enum import Enum


class SugarRole(str, Enum):
    TERM = "term"

    def __str__(self) -> str:
        return self.value
