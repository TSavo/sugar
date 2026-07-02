from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FactorySpineOffender:
    kind: str
    path: str
    line: int
    observed: str
    fix: str

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "path": self.path,
            "line": self.line,
            "observed": self.observed,
            "fix": self.fix,
        }
