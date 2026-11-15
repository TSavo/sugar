"""Python's ``list == list`` and ``tuple == tuple`` over contents this frame holds.

CPython compares two sequences of one type member by member
(``list_richcompare``, ``tuplerichcompare``): each pair is asked
``PyObject_RichCompareBool(v, w, Py_EQ)`` in order, the first pair that is
not equal decides ``False``, and when every compared pair is equal the
lengths decide.  A ``list`` asks its lengths first under ``==``: two lists
of different lengths are unequal before any member is compared.  A
``tuple`` does not: it compares the common prefix first.

This is that comparison, decided here only when every member pair it reads
is answered by the members' own ``equals`` with a decided ``True`` or
``False`` and no debt.  ``PyObject_RichCompareBool`` asks identity before
``==``; for the members admitted here (no NaN) ``v is w`` implies
``v == w``, so the identity step changes no answer.  Anything else -- a
member whose ``==`` may run source code, a member not decided, a container
whose contents are not current (``object_identity.holds_stale``) -- is not
decided here: the caller states the one undecided equality as before.
"""

from __future__ import annotations


def decided_sequence_equality(left, right, site, ctx):
    """The decided ``left == right`` for two ``list``s or two ``tuple``s, or
    None when this frame cannot decide it without reading something it does
    not hold."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    from .list_value import ListValue
    from .object_identity import holds_stale
    from .tuple_value import TupleValue

    kind = type(left)
    if kind not in (ListValue, TupleValue) or type(right) is not kind:
        return None
    if holds_stale(left) or holds_stale(right):
        return None
    left_members = tuple(left.elements)
    right_members = tuple(right.elements)
    if kind is ListValue and len(left_members) != len(right_members):
        return ExitSet.completed(FalseBoolLiteralSugar(site=site))
    for left_member, right_member in zip(left_members, right_members):
        if not (_admitted(left_member) and _admitted(right_member)):
            return None
        outcome = left_member.equals(right_member, site, ctx)
        if outcome.owed_items():
            return None
        answer = outcome.completed_value()
        if type(answer) is FalseBoolLiteralSugar:
            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        if type(answer) is not TrueBoolLiteralSugar:
            return None
    return ExitSet.completed(
        TrueBoolLiteralSugar(site=site)
        if len(left_members) == len(right_members)
        else FalseBoolLiteralSugar(site=site)
    )


def _admitted(member) -> bool:
    """A member whose ``==`` runs no source code and whose identity step
    cannot answer differently from its ``==``: a decided ``int``, ``bool``,
    ``float`` or ``complex`` other than NaN, ``None``, ``True``, ``False``,
    or a ``list``/``tuple`` (compared by this same rule)."""
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    from .list_value import ListValue
    from .none_value import NoneValue
    from .term_value import TermValue
    from .tuple_value import TupleValue

    kind = type(member)
    if kind is TermValue:
        payload = member.value
        return type(payload) in (int, bool, float, complex) and payload == payload
    return kind in (
        NoneValue,
        TrueBoolLiteralSugar,
        FalseBoolLiteralSugar,
        ListValue,
        TupleValue,
    )
