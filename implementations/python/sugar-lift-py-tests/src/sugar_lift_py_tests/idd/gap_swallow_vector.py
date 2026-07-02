from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class GapSwallowSite:
    file: str
    line: int
    caught: str
    disposition: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "caught": self.caught,
            "disposition": self.disposition,
        }


@dataclass(frozen=True)
class GapSwallowReport:
    offenders: Tuple[GapSwallowSite, ...]

    @property
    def total(self) -> int:
        return len(self.offenders)

    @property
    def is_zero(self) -> bool:
        return not self.offenders

    def to_json(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "is_zero": self.is_zero,
            "offenders": [site.to_json() for site in self.offenders],
        }
