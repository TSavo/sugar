"""``is`` on reduced objects: identity, never value equality.

A reduced list/dict/set/instance value is its CONTENTS, and a reduced
tuple/str/bytes/int/float value is its VALUE: two equal ones can be one
object or two (``[] is []`` is False; ``b = a; a is b`` is True; ``(x,) is
(x,)`` builds two tuples; whether ``1000 is 1000`` or ``"a" is "a"`` share
one object is CPython's interning and constant merging, not the language),
so the value term cannot answer ``is`` (``object_identity``).  A builtin
container, and a tuple display CPython builds at runtime, carries the
construction that made its object in the frame reading it (``allocation``,
``made_at``): two values made by different constructions are two objects
(False), and one value of one construction reaching both operands is one
object (True).  A value of another runtime type, or of another value, is
never the same object (False).  ``None``, ``True`` and ``False`` are the
language's singletons (True).  Anything else is the one comparison's own
undecided atom over this evaluation's operands.

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
# source site that made it (``made_at``, ``made_from``); a same-object
# post-state names the producing value's own; a value that arrived, was
# derived from contents that are not current, or that a builtin handed back
# from its operand names None.  A ``tuple`` names it only where a display
# CPython builds at runtime made it (``TupleSugar``); every other tuple names
# None (a tuple's contents never change, so its ``allocation`` answers
# identity only).  A ``list``/``dict``/``set`` with None names its object by
# ``arrival`` instead (``arrived``, ``arrived_as``, ``made_from``); none at
# all, and an undecided read of it refuses by name (``identity_term``).


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


def identity_term(value, site, role: str, *, owner: str):
    """The term an undecided read at ``site`` names its operand ``value`` by.

    ``value``'s own term when no container in it is stale (``holds_stale``):
    its contents are its object's contents now.  Otherwise each stale
    container in it, at any depth, is named by its identity, never by the
    contents it arrived with -- a proof states no fact about contents the
    program may no longer hold:
    ``python:object_read(<read occurrence>, <role and path>, <arrival>)``,
    the object the binding read ``arrival`` (``arrived``) handed over, as
    this read finds it.  The read's occurrence keys it because the object
    may change between two reads (``len(xs)`` twice is two unknowns); the
    arrival tells two objects one read meets apart (a ``match``'s patterns
    all read at the match).  The one place every undecided form (subscript,
    iteration, ``next``, truth, attribute, membership, length, equality, a
    binary or set operation) mints an operand's term.

    A stale operand of a read with no site is the lifter's own gap: it
    cannot key the object, so it refuses by name.  So does a stale container
    with no ``arrival``: nothing names which object it is (a read whose site
    names no coordinate, ``arrived``; a derivation with no coordinate or
    from an operand with no arrival, ``made_from``), and one term for every
    such object would let two objects one read meets share it -- a fact
    about one would be read as a fact about the other."""
    if not holds_stale(value):
        return value.to_term(owner=owner)
    if site is None:
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=None,
            owner=owner,
            observed=(
                f"undecided read of a stale {type(value).__name__} "
                "with no source site"
            ),
            requested="the read's source site, to name the object it reads",
            fix="carry the read's fragment to the floor that mints its term",
        )
    from sugar_lift_py_tests.occurrence import occurrence_key

    return _named(value, occurrence_key(site), role, owner).to_term(owner=owner)


def _named(value, key: str, path: str, owner: str, depth=0):
    """``value`` with each stale container in it replaced by its object's
    term (``identity_term``)."""
    from dataclasses import replace

    from .dict_value import DictValue
    from .guarded_value import GuardedValue
    from .list_value import ListValue
    from .set_value import SetValue
    from .symbolic_value import SymbolicValue
    from .tuple_value import TupleValue

    if contents_stale(value):
        if value.arrival is None:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=None,
                owner=owner,
                observed=(
                    f"undecided read of a stale {type(value).__name__} "
                    "that names no arrival"
                ),
                requested=(
                    "the binding read or the derivation that made the object, "
                    "to name it apart from every other object the read meets"
                ),
                fix=(
                    "give the path that made the value its arrival "
                    "(object_identity.arrived at a coordinate, made_from)"
                ),
            )
        from sugar_lift_py_tests.ir import ctor, str_const

        return SymbolicValue(
            ctor(
                "python:object_read",
                (str_const(key), str_const(path), str_const(value.arrival)),
            )
        )
    if depth > 32:
        return value
    kind = type(value)
    if kind in (ListValue, SetValue, TupleValue):
        return replace(
            value,
            elements=tuple(
                _named(element, key, f"{path}/{position}", owner, depth + 1)
                for position, element in enumerate(value.elements)
            ),
        )
    if kind is DictValue:
        return replace(
            value,
            entries=tuple(
                (
                    _named(entry, key, f"{path}/{position}k", owner, depth + 1),
                    _named(item, key, f"{path}/{position}", owner, depth + 1),
                )
                for position, (entry, item) in enumerate(value.entries)
            ),
        )
    if kind is GuardedValue:
        return replace(
            value,
            when_true=_named(value.when_true, key, path, owner, depth + 1),
            when_false=_named(value.when_false, key, path, owner, depth + 1),
        )
    return value


def made_from(op: str, site, *operands) -> dict:
    """The ``allocation`` and ``arrival`` of a new object the operation
    ``op`` at ``site`` made from ``operands``' contents (``xs + ys``,
    ``xs * 2``, a star pattern's capture, a mapping pattern's rest), as the
    keywords its constructor takes.

    Every operand current: ``made_at(site)``, and no arrival -- its contents
    are its contents.  Otherwise its contents, computed from contents the
    objects may no longer hold, are not its contents either: no
    ``allocation``, and its ``arrival`` is its derivation,
    ``<op>(<each stale operand's arrival>)@<site's occurrence>`` -- the
    object this evaluation of ``op`` made, never another's.  None when the
    site names no coordinate or a stale operand names no arrival: nothing
    names the object, and an undecided read of it refuses by name
    (``identity_term``)."""
    stale = tuple(operand for operand in operands if contents_stale(operand))
    if not stale:
        return {"allocation": made_at(site), "arrival": None}
    at = _arrival_at(site)
    arrivals = tuple(operand.arrival for operand in stale)
    if at is None or any(arrival is None for arrival in arrivals):
        return {"allocation": None, "arrival": None}
    return {"allocation": None, "arrival": f"{op}({','.join(arrivals)})@{at}"}


def arrived(value, site):
    """``value`` as it reaches a frame by binding at the read ``site``: every
    builtin container in it, at any depth, without its ``allocation``.

    Its contents are what the binding held, not the object's contents now,
    and which construction made it is not this frame's to say.  What names
    the object instead is the binding read it arrived through: a container
    with no ``arrival`` yet takes the read's occurrence
    (``occurrence.occurrence_key`` of ``site``), a member the path to it
    inside (``<read>/<position>``).  A container that already has one keeps
    it: it is still that object.  Only ``identity_term`` reads it.  A read
    whose site names no source coordinate names none: an undecided read of
    the container refuses by name (``identity_term``)."""
    memo = []

    def through():
        if not memo:
            memo.append(_arrival_at(site))
        return memo[0]

    return _arrived(value, through)


def arrived_as(value, arrival: str):
    """``value`` as it reaches a frame by a binding no source read names:
    ``arrived``, with ``arrival`` naming that binding.  A generator's frame
    holds its bindings across a yield (``generator_construction.YieldEffect``):
    each container in one is released at the yield, named by the yield's
    occurrence and the binding (``<yield occurrence>/<binding>``)."""
    return _arrived(value, lambda: arrival)


def _arrival_at(site) -> str | None:
    from sugar_lift_py_tests.occurrence import named_site_cid, occurrence_key

    if named_site_cid(site) is None:
        return None
    return occurrence_key(site)


def _arrived(value, through):
    from dataclasses import replace

    from .dict_value import DictValue
    from .guarded_value import GuardedValue
    from .list_value import ListValue
    from .set_value import SetValue
    from .tuple_value import TupleValue

    def inner(position):
        def path():
            outer = through()
            return None if outer is None else f"{outer}/{position}"

        return path

    kind = type(value)
    if kind in (ListValue, SetValue, TupleValue):
        elements = tuple(
            _arrived(element, inner(position))
            for position, element in enumerate(value.elements)
        )
        unchanged = all(a is b for a, b in zip(elements, value.elements))
        if kind is TupleValue:
            # A tuple's contents never change: it carries no arrival, only
            # the construction (identity) this frame no longer names.
            if unchanged and value.allocation is None:
                return value
            return replace(value, elements=elements, allocation=None)
        stamp = value.arrival if value.arrival is not None else through()
        if unchanged and value.allocation is None and stamp == value.arrival:
            return value
        return replace(value, elements=elements, allocation=None, arrival=stamp)
    if kind is DictValue:
        entries = tuple(
            (
                _arrived(key, inner(f"{position}k")),
                _arrived(item, inner(position)),
            )
            for position, (key, item) in enumerate(value.entries)
        )
        unchanged = all(
            a is b
            for pair, original in zip(entries, value.entries)
            for a, b in zip(pair, original)
        )
        stamp = value.arrival if value.arrival is not None else through()
        if unchanged and value.allocation is None and stamp == value.arrival:
            return value
        return replace(value, entries=entries, allocation=None, arrival=stamp)
    if kind is GuardedValue:
        when_true = _arrived(value.when_true, through)
        when_false = _arrived(value.when_false, through)
        if when_true is value.when_true and when_false is value.when_false:
            return value
        return replace(value, when_true=when_true, when_false=when_false)
    return value


def arrived_outcome(outcome, site):
    """``outcome`` with each completed value ``arrived`` at ``site``."""
    from sugar_lift_py_tests.outcome import ExitSet

    return outcome.and_then(lambda value: ExitSet.completed(arrived(value, site)))


def answers_identity_by_object(value) -> bool:
    """``value`` is a reduced object whose value term is not its object: a
    builtin container, an instance, or a ``tuple``/``str``/``bytes``/number
    value.  ``is`` with it on either side is ``object_identity``."""
    from .bytes_value import BytesValue
    from .dict_value import DictValue
    from .list_value import ListValue
    from .object_value import ObjectValue
    from .set_value import SetValue
    from .string_value import StringValue
    from .term_value import TermValue
    from .tuple_value import TupleValue

    return isinstance(
        value,
        (
            ObjectValue,
            ListValue,
            DictValue,
            SetValue,
            TupleValue,
            StringValue,
            BytesValue,
            TermValue,
        ),
    )


# The language's singletons: every ``None`` is the one ``None``, every
# ``True`` the one ``True``, every ``False`` the one ``False``.  No other
# value is promised one object (small ints, interned strings, the empty
# tuple and merged code constants are CPython's choice).
_SINGLETON_KINDS = ("None", "bool")


def object_identity(left, right, site):
    """``left is right`` asked of the objects, never of their values.

    True for one object: the same value of one construction (``allocation``)
    reaching both operands -- one evaluation, read twice (``t = (x,); t is
    t``) or handed back by a builtin as itself (``tuple(t) is t``) -- or the
    same language singleton.  False for two objects: two runtime types, two
    constructions (``(x,) is (x,)``, ``[] is []``), or two ground values (an
    object has one value).  Anything else is undecided: equal ground values
    (``1000 is 1000``, ``"a" is "a"``, ``(1, 2) is (1, 2)``: interning and
    constant merging are implementation-defined), one construction evaluated
    twice, a value that arrived."""
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import ctor, identity, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome import ExitSet

    left_made = getattr(left, "allocation", None)
    right_made = getattr(right, "allocation", None)
    left_key = _ground_key(left)
    right_key = _ground_key(right)
    if (left is right and left_made is not None) or (
        left_key is not None
        and left_key == right_key
        and left_key[0] in _SINGLETON_KINDS
    ):
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return ExitSet.completed(TrueBoolLiteralSugar(site=site))
    left_type = _known_type(left)
    right_type = _known_type(right)
    if (
        (left_type is not None and right_type is not None and left_type != right_type)
        or (
            left_made is not None and right_made is not None and left_made != right_made
        )
        or (left_key is not None and right_key is not None and left_key != right_key)
    ):
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
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    from .bytes_value import BytesValue
    from .dict_value import DictValue
    from .list_value import ListValue
    from .none_value import NoneValue
    from .object_value import ObjectValue
    from .set_value import SetValue
    from .string_value import StringValue
    from .term_value import TermValue
    from .tuple_value import TupleValue

    if isinstance(value, ObjectValue):
        return ("object", value.class_name)
    if type(value) in (TrueBoolLiteralSugar, FalseBoolLiteralSugar):
        return ("bool",)
    if type(value) is TermValue:
        payload = type(value.value)
        return (payload.__name__,) if payload in (int, float, bool, complex) else None
    for kind in (
        ListValue,
        DictValue,
        SetValue,
        NoneValue,
        StringValue,
        BytesValue,
        TupleValue,
    ):
        if type(value) is kind:
            return (kind.__name__,)
    return None


def _ground_key(value, depth=0):
    """``value``'s whole value, when this frame holds all of it, keyed by its
    runtime type: two different keys are two different values, so two
    objects.  None when any of it is not ground (a symbolic or container
    member, a guarded face).  A float keys by ``repr``: ``0.0`` and ``-0.0``
    are two values, and a NaN is never decided distinct from itself."""
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    from .bytes_value import BytesValue
    from .none_value import NoneValue
    from .string_value import StringValue
    from .term_value import TermValue
    from .tuple_value import TupleValue

    kind = type(value)
    if depth > 32:
        return None
    if kind is NoneValue:
        return ("None",)
    if kind is TrueBoolLiteralSugar:
        return ("bool", True)
    if kind is FalseBoolLiteralSugar:
        return ("bool", False)
    if kind is StringValue and type(value.value) is str:
        return ("str", value.value)
    if kind is BytesValue and type(value.value) is bytes:
        return ("bytes", value.value)
    if kind is TermValue:
        payload = value.value
        if type(payload) in (int, bool):
            return (type(payload).__name__, payload)
        if type(payload) in (float, complex):
            return (type(payload).__name__, repr(payload))
        return None
    if kind is TupleValue:
        keys = tuple(_ground_key(element, depth + 1) for element in value.elements)
        if any(element_key is None for element_key in keys):
            return None
        return ("tuple", keys)
    return None
