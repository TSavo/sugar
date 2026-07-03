from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from sugar_lift_py_tests.ir import _Atomic, _Connective, _Quantifier
from sugar_lift_py_tests.proofir._errors import proofir_construction_gap
from sugar_lift_py_tests.proofir.formulas import Formula
from sugar_lift_py_tests.proofir.sorts import Sort


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


@dataclass(frozen=True, init=False)
class PostCondition:
    formula: Formula
    formals: Mapping[str, Sort]
    out_binding: str
    out_sort: Sort
    closed: ClosedFormula

    def __init__(
        self,
        formula: Formula,
        *,
        formals: Mapping[str, Sort],
        out_binding: str = "out",
        out_sort: Sort,
    ) -> None:
        _require_tiny_formula(formula, owner="proofir.scope.PostCondition")
        if out_binding not in formula.free_vars:
            proofir_construction_gap(
                owner="proofir.scope.PostCondition",
                observed=f"free vars: {', '.join(sorted(formula.free_vars))}",
                requested=f"post mentioning {out_binding!r}",
                fix="construct the post over the verifier-visible output binding",
            )
        _require_sorted_scope(
            formula,
            formals=formals,
            extra={out_binding: out_sort},
            owner="proofir.scope.PostCondition",
        )
        closed = ClosedFormula(formula, allowed_vars=(*formals.keys(), out_binding))
        object.__setattr__(self, "formula", formula)
        object.__setattr__(self, "formals", dict(formals))
        object.__setattr__(self, "out_binding", out_binding)
        object.__setattr__(self, "out_sort", out_sort)
        object.__setattr__(self, "closed", closed)

    @property
    def ir_formula(self):
        return self.closed.ir_formula


@dataclass(frozen=True, init=False)
class PreCondition:
    formula: Formula
    formals: Mapping[str, Sort]
    closed: ClosedFormula

    def __init__(self, formula: Formula, *, formals: Mapping[str, Sort]) -> None:
        _require_tiny_formula(formula, owner="proofir.scope.PreCondition")
        _require_sorted_scope(
            formula,
            formals=formals,
            extra={},
            owner="proofir.scope.PreCondition",
        )
        closed = ClosedFormula(formula, allowed_vars=formals.keys())
        object.__setattr__(self, "formula", formula)
        object.__setattr__(self, "formals", dict(formals))
        object.__setattr__(self, "closed", closed)

    @property
    def ir_formula(self):
        return self.closed.ir_formula


def _is_ir_formula(value: object) -> bool:
    return isinstance(value, (_Atomic, _Connective, _Quantifier))


def _require_tiny_formula(formula: object, *, owner: str) -> None:
    if isinstance(formula, Formula):
        return
    observed = "naked ir.Formula" if _is_ir_formula(formula) else type(formula).__name__
    proofir_construction_gap(
        owner=owner,
        observed=observed,
        requested="typed proofir.formulas.Formula",
        fix="construct a tiny Formula before installing it in a ProofIR role",
    )


def _require_sorted_scope(
    formula: Formula,
    *,
    formals: Mapping[str, Sort],
    extra: Mapping[str, Sort],
    owner: str,
) -> None:
    allowed_sorts = {**formals, **extra}
    illegal = formula.free_vars - set(allowed_sorts)
    if illegal:
        proofir_construction_gap(
            owner=owner,
            observed=f"illegal free var(s): {', '.join(sorted(illegal))}",
            requested="free vars only from declared formals plus out",
            fix="declare the variable in the contract scope or remove it from the formula",
        )
    unsorted = sorted(name for name in formula.free_vars if name not in formula.free_var_sorts)
    if unsorted:
        proofir_construction_gap(
            owner=owner,
            observed=f"unsorted var(s): {', '.join(unsorted)}",
            requested="every var has a sort",
            fix="wrap the ir formula with an explicit sort map before constructing the condition",
        )
    mismatched = [
        name
        for name in formula.free_vars
        if name in formula.free_var_sorts
        and name in allowed_sorts
        and formula.free_var_sorts[name] != allowed_sorts[name]
    ]
    if mismatched:
        proofir_construction_gap(
            owner=owner,
            observed=", ".join(sorted(mismatched)),
            requested="formula variable sorts match the contract scope",
            fix="use one declared sort for each formal and out binding",
        )


__all__ = ["ClosedFormula", "PostCondition", "PreCondition"]
