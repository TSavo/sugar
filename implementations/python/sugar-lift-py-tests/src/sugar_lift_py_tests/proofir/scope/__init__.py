from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sugar_lift_py_tests.ir import _Atomic, _Connective, _Quantifier
from sugar_lift_py_tests.proofir._errors import proofir_construction_gap
from sugar_lift_py_tests.proofir.formulas import Formula


@dataclass(frozen=True, init=False)
class ClosedFormula:
    formula: Formula
    allowed_vars: frozenset[str]

    def __init__(
        self,
        formula: Formula,
        *,
        allowed_vars: Iterable[str] = (),
    ) -> None:
        if not isinstance(formula, Formula):
            observed = "naked ir.Formula" if _is_ir_formula(formula) else type(formula).__name__
            proofir_construction_gap(
                owner="proofir.scope.ClosedFormula",
                observed=observed,
                requested="typed proofir.formulas.Formula",
                fix="construct a tiny Formula first, then install it into ClosedFormula",
            )
        allowed = frozenset(allowed_vars)
        illegal = formula.free_vars - allowed
        if illegal:
            proofir_construction_gap(
                owner="proofir.scope.ClosedFormula",
                observed=f"illegal free var(s): {', '.join(sorted(illegal))}",
                requested="formula closed under the declared scope",
                fix="declare the variable in the role scope or remove it from the formula",
            )
        object.__setattr__(self, "formula", formula)
        object.__setattr__(self, "allowed_vars", allowed)

    @property
    def ir_formula(self):
        return self.formula.ir_formula


def _is_ir_formula(value: object) -> bool:
    return isinstance(value, (_Atomic, _Connective, _Quantifier))


__all__ = ["ClosedFormula"]
