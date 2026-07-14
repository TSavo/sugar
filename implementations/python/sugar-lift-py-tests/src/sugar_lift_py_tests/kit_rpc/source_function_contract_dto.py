from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.ir import TermTableBuilder


@dataclass(frozen=True)
class SourceFunctionContractDto:
    """Typed membrane from the source lifter into the combined DAG payload."""

    payload: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.payload.get("fnName") or self.payload.get("name") or "")

    def to_rpc_with_term_table(self, term_table: TermTableBuilder) -> dict[str, Any]:
        out = dict(self.payload)
        for role in ("pre", "post", "inv"):
            formula = out.get(role)
            if formula is not None:
                out[role] = term_table.formula_rpc(formula)
        return out
