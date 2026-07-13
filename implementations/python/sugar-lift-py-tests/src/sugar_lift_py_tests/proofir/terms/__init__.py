from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Mapping, NoReturn, TypeVar

from sugar_lift_py_tests.ir import (
    Term as IrTerm,
    _ConstBool,
    _ConstInt,
    _ConstReal,
    _ConstStr,
    _Ctor,
    _Var,
    PrimitiveSort,
    bool_const,
    ctor,
    num,
    real_lit,
    str_const,
)
from sugar_lift_py_tests.proofir._errors import proofir_construction_gap
from sugar_lift_py_tests.proofir.sorts import (
    BoolSort,
    IntSort,
    RealSort,
    Sort,
    StringSort,
    sort_from_ir,
)

S = TypeVar("S", bound=Sort)


@dataclass(frozen=True)
class Term(Generic[S]):
    sort: S
    ir_term: IrTerm
    free_vars: frozenset[str] = frozenset()
    free_var_sorts: Mapping[str, Sort] = field(default_factory=dict)


@dataclass(frozen=True, init=False)
class ConstTerm(Term[S]):
    value: object

    def __init__(self, value: object, *, sort: S) -> None:
        object.__setattr__(self, "sort", sort)
        object.__setattr__(self, "ir_term", _const_ir_term(value, sort))
        object.__setattr__(self, "free_vars", frozenset())
        object.__setattr__(self, "free_var_sorts", {})
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, init=False)
class VarTerm(Term[S]):
    name: str

    def __init__(self, name: str, *, sort: S) -> None:
        if not name:
            proofir_construction_gap(
                owner="proofir.terms.VarTerm",
                observed="empty var name",
                requested="named variable",
                fix="construct variables with the verifier-visible binding name",
            )
        object.__setattr__(self, "sort", sort)
        object.__setattr__(self, "ir_term", make_var(name))
        object.__setattr__(self, "free_vars", frozenset({name}))
        object.__setattr__(self, "free_var_sorts", {name: sort})
        object.__setattr__(self, "name", name)


@dataclass(frozen=True, init=False)
class CallTerm(Term[S]):
    callee_name: str
    args: tuple[Term[Any], ...]

    def __init__(
        self,
        callee_name: str,
        args: tuple[Term[Any], ...],
        *,
        sort: S,
    ) -> None:
        if not callee_name:
            proofir_construction_gap(
                owner="proofir.terms.CallTerm",
                observed="empty callee name",
                requested="callee name for call:<callee>",
                fix="derive EUF terms from a real callsite target",
            )
        for arg in args:
            if not isinstance(arg, Term):
                proofir_construction_gap(
                    owner="proofir.terms.CallTerm",
                    observed=type(arg).__name__,
                    requested="typed ProofIR Term argument",
                    fix="wrap ir.py terms with proofir.terms.term_from_ir first",
                )
        object.__setattr__(self, "sort", sort)
        object.__setattr__(
            self,
            "ir_term",
            ctor(f"call:{callee_name}", [arg.ir_term for arg in args]),
        )
        object.__setattr__(
            self,
            "free_vars",
            frozenset().union(*(arg.free_vars for arg in args)),
        )
        object.__setattr__(
            self,
            "free_var_sorts",
            _merge_var_sorts(*(arg.free_var_sorts for arg in args)),
        )
        object.__setattr__(self, "callee_name", callee_name)
        object.__setattr__(self, "args", args)


@dataclass(frozen=True, init=False)
class WrappedTerm(Term[S]):
    def __init__(
        self,
        ir_term: IrTerm,
        *,
        sort: S,
        free_vars: frozenset[str] = frozenset(),
        free_var_sorts: Mapping[str, Sort] | None = None,
    ) -> None:
        object.__setattr__(self, "sort", sort)
        object.__setattr__(self, "ir_term", ir_term)
        object.__setattr__(self, "free_vars", free_vars)
        object.__setattr__(self, "free_var_sorts", dict(free_var_sorts or {}))


def term_from_ir(ir_term: IrTerm, *, sort: Sort | None = None) -> Term[Any]:
    if isinstance(ir_term, _ConstInt):
        return ConstTerm(ir_term.value, sort=sort_from_ir(ir_term.sort))
    if isinstance(ir_term, _ConstStr):
        return ConstTerm(ir_term.value, sort=sort_from_ir(ir_term.sort))
    if isinstance(ir_term, _ConstBool):
        return ConstTerm(ir_term.value, sort=sort_from_ir(ir_term.sort))
    if isinstance(ir_term, _ConstReal):
        return ConstTerm(ir_term.value, sort=sort_from_ir(ir_term.sort))
    if isinstance(ir_term, _Var):
        if sort is None:
            proofir_construction_gap(
                owner="proofir.terms.term_from_ir",
                observed=f"unsorted var {ir_term.name!r}",
                requested="explicit sort for wrapped ir.Var",
                fix="carry the term sort before crossing into ProofIR membership",
            )
        return VarTerm(ir_term.name, sort=sort)
    if isinstance(ir_term, _Ctor):
        if sort is None:
            sort = Sort(
                name="LegacyCtor",
                ir_sort=PrimitiveSort("LegacyCtor"),
            )
        return WrappedTerm(
            ir_term,
            sort=sort,
            free_vars=frozenset().union(
                *(_free_vars_in_ir_term(arg) for arg in ir_term.args)
            ),
        )
    proofir_construction_gap(
        owner="proofir.terms.term_from_ir",
        observed=type(ir_term).__name__,
        requested="known ir.Term",
        fix="add a tiny proofir/terms wrapper for this term family",
    )


def _const_ir_term(value: object, sort: Sort) -> IrTerm:
    if isinstance(sort, BoolSort):
        if not isinstance(value, bool):
            _const_sort_gap(value, sort)
        return bool_const(value)
    if isinstance(sort, IntSort):
        if isinstance(value, bool) or not isinstance(value, int):
            _const_sort_gap(value, sort)
        return num(value)
    if isinstance(sort, StringSort):
        if not isinstance(value, str):
            _const_sort_gap(value, sort)
        return str_const(value)
    if isinstance(sort, RealSort):
        if not isinstance(value, str):
            _const_sort_gap(value, sort)
        return real_lit(value)
    proofir_construction_gap(
        owner="proofir.terms.ConstTerm",
        observed=sort.name,
        requested="constant-compatible sort",
        fix="add a constant constructor for this tiny sort",
    )


def _const_sort_gap(value: object, sort: Sort) -> NoReturn:
    proofir_construction_gap(
        owner="proofir.terms.ConstTerm",
        observed=f"{value!r} for {sort.name}",
        requested=f"{sort.name} literal",
        fix="construct constants with a value that matches their carried sort",
    )


def _free_vars_in_ir_term(ir_term: IrTerm) -> frozenset[str]:
    if isinstance(ir_term, _Var):
        return frozenset({ir_term.name})
    if isinstance(ir_term, _Ctor):
        return frozenset().union(*(_free_vars_in_ir_term(arg) for arg in ir_term.args))
    return frozenset()


def _merge_var_sorts(*maps: Mapping[str, Sort]) -> dict[str, Sort]:
    merged: dict[str, Sort] = {}
    for var_sorts in maps:
        for name, sort in var_sorts.items():
            previous = merged.get(name)
            if previous is not None and previous != sort:
                proofir_construction_gap(
                    owner="proofir.terms",
                    observed=f"{name}: {previous.name} vs {sort.name}",
                    requested="one sort per free variable",
                    fix="construct the formula with a single declared sort for each variable",
                )
            merged[name] = sort
    return merged


__all__ = [
    "CallTerm",
    "ConstTerm",
    "Term",
    "VarTerm",
    "WrappedTerm",
    "term_from_ir",
]
