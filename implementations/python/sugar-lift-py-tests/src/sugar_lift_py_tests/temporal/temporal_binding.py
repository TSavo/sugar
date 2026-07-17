from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class TemporalBinding:
    name: str
    value: FloorValue
    blame: str | None = None


@dataclass(frozen=True)
class GuardedTemporalBinding:
    """A one-arm binding available only while reducing the identical guard."""

    guard: Any
    binding: TemporalBinding
