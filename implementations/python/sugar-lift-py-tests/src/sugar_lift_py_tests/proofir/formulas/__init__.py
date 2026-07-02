from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from sugar_lift_py_tests.ir import Formula as IrFormula
from sugar_lift_py_tests.ir import and_ as ir_and
from sugar_lift_py_tests.ir import eq as ir_eq
from sugar_lift_py_tests.proofir._errors import proofir_construction_gap
from sugar_lift_py_tests.proofir.sorts import Sort
from sugar_lift_py_tests.proofir.terms import Term

S = TypeVar("S", bound=Sort)


@dataclass(frozen=True)
class Formula:
    ir_formula: IrFormula
    free_vars: frozenset[str] = frozenset()


@dataclass(frozen=True, init=False)
class Eq(Formula, Generic[S]):
    left: Term[S]
    right: Term[S]

    def __init__(self, left: Term[S], right: Term[S]) -> None:
        if not isinstance(left, Term) or not isinstance(right, Term):
            proofir_construction_gap(
                owner="proofir.formulas.Eq",
                observed=f"{type(left).__name__}, {type(right).__name__}",
                requested="typed ProofIR terms",
                fix="construct Eq from proofir.terms.Term values, never raw ir terms",
            )
        if not (
            left.sort == right.sort
            or left.sort.is_explicitly_coercible_to(right.sort)
            or right.sort.is_explicitly_coercible_to(left.sort)
        ):
            proofir_construction_gap(
                owner="proofir.formulas.Eq",
                observed=f"{left.sort.name} vs {right.sort.name}",
                requested="matching sorts for Eq",
                fix="use matching term sorts or insert an explicit coercion before Eq",
            )
        object.__setattr__(self, "ir_formula", ir_eq(left.ir_term, right.ir_term))
        object.__setattr__(self, "free_vars", left.free_vars | right.free_vars)
        object.__setattr__(self, "left", left)
        object.__setattr__(self, "right", right)


@dataclass(frozen=True, init=False)
class And(Formula):
    operands: tuple[Formula, ...]

    def __init__(self, operands: tuple[Formula, ...]) -> None:
        for operand in operands:
            if not isinstance(operand, Formula):
                proofir_construction_gap(
                    owner="proofir.formulas.And",
                    observed=type(operand).__name__,
                    requested="typed ProofIR Formula operand",
                    fix="wrap formulas in the tiny ProofIR formula family first",
                )
        object.__setattr__(
            self,
            "ir_formula",
            ir_and([operand.ir_formula for operand in operands]),
        )
        object.__setattr__(
            self,
            "free_vars",
            frozenset().union(*(operand.free_vars for operand in operands)),
        )
        object.__setattr__(self, "operands", operands)


__all__ = ["And", "Eq", "Formula"]
