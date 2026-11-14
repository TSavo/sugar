"""``is`` on reduced mutable objects: identity, never value equality.

A reduced list/dict/set/instance value is its CONTENTS: two equal contents
can be one object or two (``[] is []`` is False; ``b = a; a is b`` is True),
so the value term cannot answer ``is``.  The one comparison is its own
undecided atom over this evaluation's operands; a value of another runtime
type is never the same object (False); a decided source identity is answered
before reduction (``container_mutation.decided_identity``).
"""

from __future__ import annotations


def _known_type(value):
    from .dict_value import DictValue
    from .list_value import ListValue
    from .none_value import NoneValue
    from .object_value import ObjectValue
    from .set_value import SetValue
    from .string_value import StringValue
    from .tuple_value import TupleValue

    if isinstance(value, ObjectValue):
        return ("object", value.class_name)
    for kind in (ListValue, DictValue, SetValue, NoneValue, StringValue, TupleValue):
        if type(value) is kind:
            return (kind.__name__,)
    return None


def mutable_object_identity(left, right, site):
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import ctor, identity, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome import ExitSet

    left_type = _known_type(left)
    right_type = _known_type(right)
    if left_type is not None and right_type is not None and left_type != right_type:
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        return ExitSet.completed(FalseBoolLiteralSugar(site=site))
    key = str_const(occurrence_key(site))
    return ExitSet.completed(
        PredicateValue(
            identity(
                ctor("python:object_at", (key, str_const("left"))),
                ctor("python:object_at", (key, str_const("right"))),
            ),
            site,
            operand_callsites=(*left.callsites(), *right.callsites()),
        )
    )
