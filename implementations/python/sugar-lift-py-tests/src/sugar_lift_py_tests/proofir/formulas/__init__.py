from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Generic, Mapping, TypeVar

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.ir import Formula as IrFormula
from sugar_lift_py_tests.ir import Term as IrTerm
from sugar_lift_py_tests.ir import _Atomic, _Connective, _Ctor, _Quantifier, _Var
from sugar_lift_py_tests.ir import and_ as ir_and
from sugar_lift_py_tests.ir import eq as ir_eq
from sugar_lift_py_tests.ir import formula_to_value
from sugar_lift_py_tests.proofir._errors import proofir_construction_gap
from sugar_lift_py_tests.proofir.sorts import Sort
from sugar_lift_py_tests.proofir.terms import Term

S = TypeVar("S", bound=Sort)


@dataclass(frozen=True)
class Formula:
    ir_formula: IrFormula
    free_vars: frozenset[str] = frozenset()
    free_var_sorts: Mapping[str, Sort] = field(default_factory=dict)


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
        if left.sort != right.sort:
            proofir_construction_gap(
                owner="proofir.formulas.Eq",
                observed=f"{left.sort.name} vs {right.sort.name}",
                requested="matching sorts for Eq",
                fix="use matching term sorts; construct an explicit coercion term before Eq",
            )
        object.__setattr__(self, "ir_formula", ir_eq(left.ir_term, right.ir_term))
        object.__setattr__(self, "free_vars", left.free_vars | right.free_vars)
        object.__setattr__(
            self,
            "free_var_sorts",
            _merge_var_sorts(left.free_var_sorts, right.free_var_sorts),
        )
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
        object.__setattr__(
            self,
            "free_var_sorts",
            _merge_var_sorts(*(operand.free_var_sorts for operand in operands)),
        )
        object.__setattr__(self, "operands", operands)


def formula_from_ir(
    ir_formula: IrFormula,
    *,
    var_sorts: Mapping[str, Sort],
) -> Formula:
    free_vars = _free_vars_in_ir_formula(ir_formula)
    carried_sorts = {name: var_sorts[name] for name in free_vars if name in var_sorts}
    return Formula(
        ir_formula=ir_formula,
        free_vars=free_vars,
        free_var_sorts=carried_sorts,
    )


def formula_to_rpc(formula: Formula) -> dict[str, Any]:
    if not isinstance(formula, Formula):
        proofir_construction_gap(
            owner="proofir.formulas.formula_to_rpc",
            observed=type(formula).__name__,
            requested="typed proofir.formulas.Formula",
            fix="wrap the ir formula before diagnostic serialization",
        )
    return json.loads(encode_jcs(formula_to_value(formula.ir_formula)))


def _merge_var_sorts(*maps: Mapping[str, Sort]) -> dict[str, Sort]:
    merged: dict[str, Sort] = {}
    for var_sorts in maps:
        for name, sort in var_sorts.items():
            previous = merged.get(name)
            if previous is not None and previous != sort:
                proofir_construction_gap(
                    owner="proofir.formulas",
                    observed=f"{name}: {previous.name} vs {sort.name}",
                    requested="one sort per free variable",
                    fix="construct formulas with a single declared sort for each variable",
                )
            merged[name] = sort
    return merged


def _free_vars_in_ir_formula(
    ir_formula: IrFormula, memo: "dict[int, frozenset[str]] | None" = None
) -> frozenset[str]:
    # Terms form a shared DAG (term-refs alias one canonical row from many
    # parents), so the traversal memoizes per node identity: without it every
    # shared subterm is revisited once per PATH, which is exponential on deep
    # DAGs. The memo is per top-level call; the formula being traversed pins
    # every node alive, so id() keys cannot be reused within the call.
    if memo is None:
        memo = {}
    if isinstance(ir_formula, _Atomic):
        return frozenset().union(
            *(_free_vars_in_ir_term(term, memo) for term in ir_formula.args)
        )
    if isinstance(ir_formula, _Connective):
        return frozenset().union(
            *(
                _free_vars_in_ir_formula(operand, memo)
                for operand in ir_formula.operands
            )
        )
    if isinstance(ir_formula, _Quantifier):
        return _free_vars_in_ir_formula(ir_formula.body, memo) - {ir_formula.name}
    proofir_construction_gap(
        owner="proofir.formulas.formula_from_ir",
        observed=type(ir_formula).__name__,
        requested="known ir.Formula",
        fix="wrap only ir.py formula values in the ProofIR formula family",
    )


def _free_vars_in_ir_term(
    ir_term: IrTerm, memo: "dict[int, frozenset[str]] | None" = None
) -> frozenset[str]:
    if memo is None:
        memo = {}
    cached = memo.get(id(ir_term))
    if cached is not None:
        return cached
    if isinstance(ir_term, _Var):
        result = frozenset({ir_term.name})
    elif isinstance(ir_term, _Ctor):
        result = frozenset().union(
            *(_free_vars_in_ir_term(arg, memo) for arg in ir_term.args)
        )
    else:
        result = frozenset()
    memo[id(ir_term)] = result
    return result


__all__ = ["And", "Eq", "Formula", "formula_from_ir", "formula_to_rpc"]
