from __future__ import annotations

from typing import Literal

from sugar_lift_py_tests.ir import (
    Formula,
    Term,
    _ConstBool,
    _ConstInt,
    _ConstReal,
    _ConstStr,
    _Ctor,
    ctor,
    eq,
    implies,
    py_eq,
)

from .floor_value import FloorValue

EqualitySort = Literal["Int", "Real", "Bool", "String"]


def _term_sort(term: Term) -> EqualitySort | None:
    if isinstance(term, _ConstInt):
        return "Int"
    if isinstance(term, _ConstReal):
        return "Real"
    if isinstance(term, _ConstBool):
        return "Bool"
    if isinstance(term, _ConstStr):
        return "String"
    if isinstance(term, _Ctor) and term.name in {"+", "-", "*", "//", "%"}:
        operand_sorts = tuple(_term_sort(operand) for operand in term.args)
        if (
            operand_sorts
            and operand_sorts[0] in {"Int", "Real"}
            and all(sort == operand_sorts[0] for sort in operand_sorts)
        ):
            return operand_sorts[0]
    return None


def _sort_warrant(value: FloorValue, term: Term, *, owner: str) -> EqualitySort | None:
    # A computed opaque operation warrants the sort of its coordinate without
    # replacing that coordinate. This is testimony attached at construction.
    from .opaque_op_callsite import OpaqueOpCallsite

    if isinstance(value, OpaqueOpCallsite) and value.computed is not None:
        computed = value.computed.to_term(owner=owner)
        return _term_sort(computed)
    return _term_sort(term)


def resolve_equality_atom(
    left: FloorValue,
    right: FloorValue,
    *,
    owner: str,
) -> tuple[Formula, tuple[Formula, ...]]:
    """Resolve Python equality once, before an atom can enter ProofIR.

    #4371 ruling (T): per-atom by sort warrant — same-sort → FOL ``=``;
    Int/Real → ``py.eq`` + explicit ``to_real`` bridge; opaque → ``py.eq``.
    Sole construction door for equality vocabulary (also chained Eq/NotEq).
    """
    left_term = left.to_term(owner=owner)
    right_term = right.to_term(owner=owner)
    left_sort = _sort_warrant(left, left_term, owner=owner)
    right_sort = _sort_warrant(right, right_term, owner=owner)

    if left_sort is not None and left_sort == right_sort:
        return eq(left_term, right_term), ()

    stated = py_eq(left_term, right_term)
    if {left_sort, right_sort} == {"Int", "Real"}:
        int_term, real_term = (
            (left_term, right_term) if left_sort == "Int" else (right_term, left_term)
        )
        # This is an explicit platform bridge carried beside the stated py.eq;
        # no term is silently cast and no mixed-sort bare equality is built.
        bridge = implies(stated, eq(ctor("to_real", [int_term]), real_term))
        return stated, (bridge,)

    return stated, ()
