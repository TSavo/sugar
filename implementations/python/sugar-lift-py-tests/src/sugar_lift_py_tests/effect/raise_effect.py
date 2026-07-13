from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RaiseEffect:
    exception_name: str | None = None
    blame: str | None = None
    source_sha256: str | None = None

    @property
    def reason(self) -> str:
        name = self.exception_name or "unknown exception"
        locus = f" at {self.blame}" if self.blame is not None else ""
        return (
            f"raise {name}{locus}: a Python raise effect that exits the current "
            "block and may be routed by a matching TrySugar handler"
        )
