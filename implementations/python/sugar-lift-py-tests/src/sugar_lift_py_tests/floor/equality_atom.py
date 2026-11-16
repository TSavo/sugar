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


def equality_runs_no_source(value, depth: int = 0) -> bool:
    """Whether ``==`` with ``value`` as either operand runs no code the
    lift did not read, against another such value: a decided builtin scalar
    (``int``, ``float``, ``bool``, ``complex``, ``str``, ``bytes``,
    ``None``, ``...``, the length a successful ``len`` returns), or a
    ``list`` / ``tuple`` / ``set`` / ``dict`` whose every member (key and
    value) is one, read where its contents are current.

    CPython's ``==`` over two such values is the builtin types' own
    ``__eq__`` (and its reflection, then identity): it completes, so the
    stated equality is its whole answer.  Anything else -- a formal, a call
    result, an instance, a class object, an effect slot, a comprehension
    whose members are not in hand, a container holding any of them, a
    module global another function may have changed, a comparison's value
    -- selects an ``__eq__`` (its own, a member's, a reflection) this frame
    did not look at, which may raise anything (the #7585 law): the one
    undecided equality (:func:`answered_equality`)."""
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    from .bytes_value import BytesValue
    from .complex_value import ComplexValue
    from .dict_value import DictValue
    from .ellipsis_value import EllipsisValue
    from .list_value import ListValue
    from .none_value import NoneValue
    from .object_identity import contents_stale
    from .set_value import SetValue
    from .string_value import StringValue
    from .term_value import TermValue
    from .tuple_coordinate_value import TupleLengthValue
    from .tuple_value import TupleValue

    kind = type(value)
    if kind in (
        TermValue,
        StringValue,
        BytesValue,
        ComplexValue,
        NoneValue,
        EllipsisValue,
        TrueBoolLiteralSugar,
        FalseBoolLiteralSugar,
        TupleLengthValue,
    ):
        return True
    if depth > 32 or contents_stale(value):
        return False
    if kind in (ListValue, TupleValue, SetValue):
        return all(
            equality_runs_no_source(element, depth + 1) for element in value.elements
        )
    if kind is DictValue:
        return all(
            equality_runs_no_source(key, depth + 1)
            and equality_runs_no_source(item, depth + 1)
            for key, item in value.entries
        )
    return False


def answered_equality(left: FloorValue, right: FloorValue, predicate, site):
    """The floor's one answer for ``left == right`` it stated as
    ``predicate`` (``resolve_equality_atom``): that predicate, completed,
    where neither operand's ``==`` runs code the lift did not read
    (:func:`equality_runs_no_source`); else the one undecided equality, two
    faced (``comparison_op_sugar.undecided_dispatch_faces``): the keyed
    ``python:compare_result("Eq", ...)`` truth completes only under its
    ``python:compare.completes`` atom and an undetermined halt (owner
    ``UndecidedCompare:Eq``) stands under the complement, owed either way.

    The value type answers its own equality here, at the floor, never a
    halt patched onto a bare ``py.eq`` afterwards (#7757).  ``!=`` stands
    on this same answer and negates its completed truth only."""
    from sugar_lift_py_tests.outcome import ExitSet

    if equality_runs_no_source(left) and equality_runs_no_source(right):
        return ExitSet.completed(predicate)
    from sugar_lift_py_tests.sugar.comparison_op_sugar import (
        undecided_dispatch_faces,
    )

    return undecided_dispatch_faces(predicate, site, "Eq")
