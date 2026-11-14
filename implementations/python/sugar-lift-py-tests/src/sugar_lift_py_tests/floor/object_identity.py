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

# There is no default ``allocation``: every ``list``/``dict``/``set`` value
# constructor names it (a required keyword).  A fresh object names the
# source site that made it (``made_at``, ``made_if_current``); a same-object
# post-state names the producing value's own; a value that arrived, was
# derived from contents that are not current, or that a builtin handed back
# from its operand names None.


def made_at(site) -> str | None:
    """The ``allocation`` of an object a construction at ``site`` made.

    The site's source coordinate (``occurrence.named_site_cid``), never its
    occurrence path: one construction evaluated twice (an unrolled loop, a
    re-entered body) makes two objects a single site cannot tell apart, so
    two values made at one site are never decided distinct.  None for a
    site that names no source coordinate: the construction is not one this
    frame can name, so its contents are not read (``contents_current``)."""
    from sugar_lift_py_tests.occurrence import named_site_cid

    return named_site_cid(site)


def contents_current(value) -> bool:
    """Whether ``value``'s contents are its object's contents now: a
    construction in this frame made it, or it is the one door's post-state
    of such an object.

    The one currency rule: every read of a builtin container's contents asks
    it -- the cited fold (``_host_ground``), the one door's container law
    (``builtin_container_method.apply``), and each floor read (``len``,
    subscript and slicing, iteration and unpacking, ``in``, ``==``).  A
    container that is not current (``contents_stale``) is read in the read's
    own undecided form, never from the contents it holds."""
    return getattr(value, "allocation", None) is not None


def contents_stale(value) -> bool:
    """``value`` is a ``list``/``dict``/``set`` whose contents are not
    current (``contents_current``): no read takes them."""
    from .dict_value import DictValue
    from .list_value import ListValue
    from .set_value import SetValue

    return type(value) in (ListValue, DictValue, SetValue) and not contents_current(
        value
    )


def holds_stale(value, depth=0) -> bool:
    """``value``, or a container in it at any depth, is ``contents_stale``: a
    read of all of ``value``'s contents (``==``) would read stale ones."""
    from .dict_value import DictValue
    from .guarded_value import GuardedValue
    from .list_value import ListValue
    from .set_value import SetValue
    from .tuple_value import TupleValue

    if depth > 32 or contents_stale(value):
        return True
    kind = type(value)
    if kind in (ListValue, SetValue, TupleValue):
        return any(holds_stale(element, depth + 1) for element in value.elements)
    if kind is DictValue:
        return any(
            holds_stale(key, depth + 1) or holds_stale(item, depth + 1)
            for key, item in value.entries
        )
    if kind is GuardedValue:
        return holds_stale(value.when_true, depth + 1) or holds_stale(
            value.when_false, depth + 1
        )
    return False


def made_if_current(site, *operands) -> str | None:
    """The ``allocation`` of a new object an operation at ``site`` made from
    ``operands``' contents (``xs + ys``, ``xs[1:]``, ``s | t``): ``made_at``
    when every operand's contents are current, else None -- contents computed
    from stale ones are not the new object's contents either."""
    if any(contents_stale(operand) for operand in operands):
        return None
    return made_at(site)


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
