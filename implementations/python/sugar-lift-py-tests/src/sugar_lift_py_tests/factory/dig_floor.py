# SPDX-License-Identifier: MIT OR Apache-2.0
"""Dig-floor provenance: warranting assertion locus at floor emission (#4016 Crime 2).

A dig that floors into a literal or effect must carry the stated assertion that
warranted the dig. Absence of that stamp is a forged warrant (Crime 2).

Report-side only — does not alter FOL/EUF fact bytes (verdict-neutral).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


FloorKind = Literal["literal", "effect"]


@dataclass(frozen=True)
class DigFloorRecord:
    """One dig-floor emission: a ground produced by dig reduction."""

    floor: FloorKind
    file: str
    line: int
    col: int
    blame: str
    detail: str
    callee: str | None = None
    # None ⇒ Crime 2 (forged warrant): floor with no stated assert authorizing it.
    warranting_assert: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": "dig-floor",
            "floor": self.floor,
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "blame": self.blame,
            "detail": self.detail,
        }
        if self.callee is not None:
            out["callee"] = self.callee
        # Explicit null when absent — detector keys on this field.
        out["warrantingAssert"] = self.warranting_assert
        return out

    @property
    def is_forged_warrant(self) -> bool:
        return self.warranting_assert is None


def assert_locus_json(
    *,
    file: str,
    line: int,
    col: int = 0,
) -> dict[str, Any]:
    return {"file": file, "line": int(line), "col": int(col)}


def record_dig_floor(
    dig_floors: list[DigFloorRecord],
    *,
    floor: FloorKind,
    file: str,
    line: int,
    col: int = 0,
    blame: str,
    detail: str,
    callee: str | None = None,
    warranting_assert: dict[str, Any] | None,
) -> None:
    dig_floors.append(
        DigFloorRecord(
            floor=floor,
            file=file,
            line=int(line),
            col=int(col),
            blame=blame,
            detail=detail,
            callee=callee,
            warranting_assert=warranting_assert,
        )
    )
