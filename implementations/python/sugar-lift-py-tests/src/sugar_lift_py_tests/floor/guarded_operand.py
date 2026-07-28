"""A binary operation whose RIGHT operand is split by a guard.

``GuardedValue`` already owns both directions of this distribution:
``_map`` / ``_predicate`` when the guarded value is the receiver, and
``map_from_left`` / ``predicate_from_left`` when it is the right operand. The
second door was being reached ad hoc -- ``TermValue.add``, ``SymbolicValue
.multiply``, ``FloorValue.less_than`` and ``CallSiteValue`` each wrote the
check, and every receiver that did NOT write it panicked instead
(``StringValue.contains`` observing a ``GuardedValue`` needle: "string needle,
symbolic membership operand, or typed TypeError" -- and a guarded needle is
none of those three, because it is not ONE needle at all).

A guarded operand is not a value category a membership law has to answer for.
It is two operands under one guard, and the answer is the two answers rejoined
under that same guard. Distributing FIRST means each receiver law only ever
sees an unguarded operand, which is the operand shape it was written for. The
guard is read from the operand's own construction, never from a type name in
source.
"""

from __future__ import annotations


def distribute_guarded_predicate(receiver, operand, method: str, site):
    """The rejoined predicate, or ``None`` when the operand carries no guard.

    ``None`` is "this door does not apply", never a soft answer: the caller
    falls through to its own law, whose None arm is still the honest no.
    """
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue

    if not isinstance(operand, GuardedValue):
        return None
    return operand.predicate_from_left(method, receiver, site)
