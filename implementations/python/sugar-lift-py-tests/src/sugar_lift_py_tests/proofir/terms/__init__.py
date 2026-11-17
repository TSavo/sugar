from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Mapping, NoReturn, TypeVar

from sugar_lift_py_tests.call_symbol import call_symbol
from sugar_lift_py_tests.ir import (
    Term as IrTerm,
    _Atomic,
    _Connective,
    _ConstBool,
    _ConstInt,
    _ConstReal,
    _ConstStr,
    _Ctor,
    _Lambda,
    _Quantifier,
    _Var,
    PrimitiveSort,
    bool_const,
    ctor,
    make_var,
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
            ctor(
                call_symbol(callee_name),
                [arg.ir_term for arg in args],
                symbol_kind="coordinate",
            ),
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
    if isinstance(ir_term, _Lambda):
        if sort is None:
            sort = Sort(
                name="LegacyLambda",
                ir_sort=PrimitiveSort("LegacyLambda"),
            )
        body_free_vars = _free_vars_in_ir_term(ir_term.body)
        free_vars = body_free_vars - {ir_term.param_name}
        free_var_sorts = {name: sort for name in body_free_vars}
        free_var_sorts.pop(ir_term.param_name, None)
        return WrappedTerm(
            ir_term,
            sort=sort,
            free_vars=free_vars,
            free_var_sorts=free_var_sorts,
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


def _free_vars_in_ir_term(
    ir_term: IrTerm, memo: "dict[int, frozenset[str]] | None" = None
) -> frozenset[str]:
    return free_vars_in_ir(ir_term, formula=False, memo=memo)


def free_vars_in_ir(
    root: object,
    *,
    formula: bool,
    memo: "dict[int, frozenset[str]] | None" = None,
) -> frozenset[str]:
    """The one reader of an ir term's or formula's free variables.

    Iterative post-order over the shared DAG: a formula a long body folds
    (an ``and`` nested once per statement) is as deep as the body is long, so
    a recursive walk ran out of Python stack and the file's mint died with
    no proof. Memoized per node identity, because term-refs alias one
    canonical row from many parents; the root pins every node alive for the
    call, so ``id()`` keys are not reused. A node met again while its own
    children are still open is a cycle, refused by name like any other
    unknown shape.
    """
    if memo is None:
        memo = {}
    open_nodes: set[int] = set()
    stack: list[tuple[object, bool, bool]] = [(root, formula, False)]
    while stack:
        node, in_formula, children_done = stack.pop()
        key = id(node)
        if not children_done and key in memo:
            continue
        if in_formula:
            if isinstance(node, _Atomic):
                children = tuple((arg, False) for arg in node.args)
                bound: str | None = None
            elif isinstance(node, _Connective):
                children = tuple((operand, True) for operand in node.operands)
                bound = None
            elif isinstance(node, _Quantifier):
                children = ((node.body, True),)
                bound = node.name
            else:
                proofir_construction_gap(
                    owner="proofir.formulas.formula_from_ir",
                    observed=type(node).__name__,
                    requested="known ir.Formula",
                    fix="wrap only ir.py formula values in the ProofIR formula family",
                )
        elif isinstance(node, _Var):
            memo[key] = frozenset({node.name})
            continue
        elif isinstance(node, _Ctor):
            children = tuple((arg, False) for arg in node.args)
            bound = None
        elif isinstance(node, _Lambda):
            children = ((node.body, False),)
            bound = node.param_name
        else:
            memo[key] = frozenset()
            continue
        if children_done:
            open_nodes.discard(key)
            found = frozenset().union(*(memo[id(child)] for child, _ in children))
            memo[key] = found - {bound} if bound is not None else found
            continue
        if key in open_nodes:
            proofir_construction_gap(
                owner="proofir.formulas.formula_from_ir",
                observed=f"cyclic {type(node).__name__}",
                requested="an acyclic ir term or formula",
                fix="build ir values bottom-up; a node never contains itself",
            )
        open_nodes.add(key)
        stack.append((node, in_formula, True))
        stack.extend(
            (child, child_in_formula, False)
            for child, child_in_formula in reversed(children)
            if id(child) not in memo
        )
    return memo[id(root)]


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
