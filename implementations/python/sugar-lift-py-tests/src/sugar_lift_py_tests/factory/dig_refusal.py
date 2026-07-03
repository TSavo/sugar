from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DigRefusal:
    """A tower the digger declined to climb, recorded instead of hidden."""

    callee: str
    blame: str
    caught: str
    reason: str

    def to_json(self) -> dict[str, Any]:
        from sugar_lift_py_tests.proofir.nodes.refusal_record import RefusalRecord

        return RefusalRecord.dig_refusal_diagnostic(self)

    def to_rpc(self) -> dict[str, Any]:
        return self.to_json()
