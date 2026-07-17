from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term


@dataclass(frozen=True)
class RaiseEffect:
    exception_name: str | None = None
    blame: str | None = None
    source_sha256: str | None = None
    exception_type_coordinate: Term | None = None

    @property
    def reason(self) -> str:
        name = self.exception_name or (
            repr(self.exception_type_coordinate)
            if self.exception_type_coordinate is not None
            else "unknown exception"
        )
        locus = f" at {self.blame}" if self.blame is not None else ""
        return (
            f"raise {name}{locus}: a Python raise effect that exits the current "
            "block and may be routed by a matching TrySugar handler"
        )
