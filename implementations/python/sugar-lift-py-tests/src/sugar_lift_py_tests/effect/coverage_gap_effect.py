from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoverageGapEffect:
    boundary: str
    reason: str
