"""``is`` on reduced mutable objects: identity, never value equality.

A reduced list/dict/set/instance value is its CONTENTS: two equal contents
can be one object or two (``[] is []`` is False; ``b = a; a is b`` is True),
so the value term cannot answer ``is``.  A builtin container carries the
construction that made its object in the frame reading it (``allocation``,
``made_at``): two values made by different constructions are two objects
(False).  A value of another runtime type is never the same object (False).
Anything else is the one comparison's own undecided atom over this
evaluation's operands.

The same ``allocation`` says whether a container's contents are the
object's contents now (``contents_current``): this frame threads every
change to an object it made through the one mutation door, whose post-state
keeps the object's ``allocation``.  A value that reaches a frame by binding
(a parameter's actual, a global, an attribute, a callee's return, a yielded
value) carries none (``arrived``): code this frame does not see may have
changed it since its contents were read.
"""

from __future__ import annotations


def made_at(site) -> str | None:
    """The ``allocation`` of an object a construction at ``site`` made.

    The site's source coordinate (``occurrence.site_coordinate_cid``),
    never its occurrence path: one construction evaluated twice (an unrolled
    loop, a re-entered body) makes two objects a single site cannot tell
    apart, so two values made at one site are never decided distinct.  None
    for a site with no source coordinate."""
    if not (hasattr(site, "line_col_span") and hasattr(site, "source_cid")):
        return None
    from sugar_lift_py_tests.occurrence import site_coordinate_cid

    return site_coordinate_cid(site)


def contents_current(value) -> bool:
    """Whether ``value``'s contents are its object's contents now: a
    construction in this frame made it, or it is the one door's post-state
    of such an object."""
    return getattr(value, "allocation", None) is not None


def arrived(value):
    """``value`` as it reaches a frame by binding: every builtin container in
    it, at any depth, without its ``allocation``.

    Its contents are what the binding held, not the object's contents now,
    and which construction made it is not this frame's to say."""
    from dataclasses import replace

    from .dict_value import DictValue
    from .guarded_value import GuardedValue
    from .list_value import ListValue
    from .set_value import SetValue
    from .tuple_value import TupleValue

    kind = type(value)
    if kind in (ListValue, SetValue, TupleValue):
        elements = tuple(arrived(element) for element in value.elements)
        unchanged = all(a is b for a, b in zip(elements, value.elements))
        if unchanged and getattr(value, "allocation", None) is None:
            return value
        if kind is TupleValue:
            return replace(value, elements=elements)
        return replace(value, elements=elements, allocation=None)
    if kind is DictValue:
        entries = tuple((arrived(key), arrived(item)) for key, item in value.entries)
        unchanged = all(
            a is b
            for pair, original in zip(entries, value.entries)
            for a, b in zip(pair, original)
        )
        if unchanged and value.allocation is None:
            return value
        return replace(value, entries=entries, allocation=None)
    if kind is GuardedValue:
        when_true = arrived(value.when_true)
        when_false = arrived(value.when_false)
        if when_true is value.when_true and when_false is value.when_false:
            return value
        return replace(value, when_true=when_true, when_false=when_false)
    return value


def arrived_outcome(outcome):
    """``outcome`` with each completed value ``arrived``."""
    from sugar_lift_py_tests.outcome import ExitSet

    return outcome.and_then(lambda value: ExitSet.completed(arrived(value)))


def mutable_object_identity(left, right, site):
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import ctor, identity, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome import ExitSet

    left_type = _known_type(left)
    right_type = _known_type(right)
    left_made = getattr(left, "allocation", None)
    right_made = getattr(right, "allocation", None)
    if (
        left_type is not None and right_type is not None and left_type != right_type
    ) or (left_made is not None and right_made is not None and left_made != right_made):
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
