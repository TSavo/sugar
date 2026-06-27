from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceSpanDto:
    start_line: int
    start_col: int = 0
    end_line: int | None = None
    end_col: int = 0

    def to_rpc(self) -> dict[str, Any]:
        return {
            "start_line": self.start_line,
            "start_col": self.start_col,
            "end_line": self.end_line if self.end_line is not None else self.start_line,
            "end_col": self.end_col,
        }
