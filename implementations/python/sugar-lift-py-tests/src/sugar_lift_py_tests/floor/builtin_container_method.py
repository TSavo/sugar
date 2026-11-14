"""CPython's documented mutating methods on a decided ``list``/``dict``/``set``.

A method call whose receiver is a constructed ``ListValue``/``DictValue``/
``SetValue`` (the lifter's own floor for a ``builtins.list``/``dict``/``set``)
is cited from the Python Library Reference, "Built-in Types":

- *Mutable Sequence Types* (``list``): ``append``, ``extend``, ``insert``,
  ``pop``, ``remove``, ``clear``, ``reverse``, ``s[i] = x``, ``del s[i]``;
  ``sort`` without ``key``/``reverse`` over a homogeneous ground run.
- *Mapping Types* (``dict``): ``d[k] = v``, ``del d[k]``, ``update``,
  ``setdefault``, ``pop``, ``popitem``, ``clear``.
- *Set Types* (``set``): ``add``, ``discard``, ``remove``, ``pop`` of a
  one-member set, ``clear``, ``update``.

``apply`` answers the pair ``(post-state, result)`` -- the receiver's
contents after the call and the call's value (``None`` for every mutator but
``pop``/``setdefault``/``popitem``) -- or the call's decided exceptional exit
(``IndexError`` popping an empty list or out of range, ``ValueError`` removing a
missing member, ``KeyError`` for a missing key or an empty ``popitem``/``pop``,
``TypeError`` for an unhashable key or member). It answers ``None`` when the
operands do not decide the effect (a symbolic member's equality, a non-ground
index, an iterable without finite members): the caller keeps that call opaque
and the receiver's contents unknown afterwards. It never guesses an arm.
"""

from __future__ import annotations

UNDECIDED = None

# Methods of each built-in container that change the receiver, read only for
# a value already decided to be that container (``container_kind``): what a
# method call does to any other value is not decided by its spelling.
MUTATING_METHODS = {
    "list": frozenset(
        {
            "append",
            "extend",
            "insert",
            "pop",
            "remove",
            "clear",
            "reverse",
            "sort",
            "__setitem__",
            "__delitem__",
            "__iadd__",
            "__imul__",
        }
    ),
    "dict": frozenset(
        {
            "__setitem__",
            "__delitem__",
            "update",
            "setdefault",
            "pop",
            "popitem",
            "clear",
            "__ior__",
        }
    ),
    "set": frozenset(
        {
            "add",
            "discard",
            "remove",
            "pop",
            "clear",
            "update",
            "difference_update",
            "intersection_update",
            "symmetric_difference_update",
            "__ior__",
            "__iand__",
            "__isub__",
            "__ixor__",
        }
    ),
}

# Cited methods whose exits and result the law decides from the operands
# alone, never from the receiver's contents.  On a receiver whose contents
# are not current (``object_identity.contents_current``) only these are
# applied; the post-state they leave is not current either (each post-state
# is the receiver's own object and names the receiver's ``allocation``).
CONTENTS_FREE_METHODS = {
    "list": frozenset({"append", "extend", "insert", "clear", "reverse"}),
    "dict": frozenset({"__setitem__", "update", "clear"}),
    "set": frozenset(
        {
            "add",
            "discard",
            "update",
            "clear",
            "difference_update",
            "intersection_update",
            "symmetric_difference_update",
        }
    ),
}


def container_kind(value) -> str | None:
    """``list``/``dict``/``set`` for the lifter's own constructed containers."""
    from .dict_value import DictValue
    from .list_value import ListValue
    from .set_value import SetValue

    if type(value) is ListValue:
        return "list"
    if type(value) is DictValue:
        return "dict"
    if type(value) is SetValue:
        return "set"
    return None


def _pair(post, result):
    from .tuple_value import TupleValue
    from sugar_lift_py_tests.outcome import ExitSet

    return ExitSet.completed(TupleValue((post, result)))


def _none():
    from .none_value import NoneValue

    return NoneValue()


def _raise(name, site, owner):
    from .ground_exit import ground_exceptional_exit

    return ground_exceptional_exit(exception_name=name, site=site, owner=owner)


def _ground_int(value):
    from .term_value import TermValue

    if type(value) is TermValue and type(value.value) is int:
        return value.value
    return None


def _equal(left, right):
    """Closed ``x is e or x == e`` of two members: True, False, or None
    (undecided). One law with membership (``floor/membership.py``)."""
    from .membership import member_equal

    decision = member_equal(left, right)
    if decision is NotImplemented:
        return None
    return decision


def _unhashable(value) -> bool:
    """A decided unhashable key/member: a list/dict/set, or a tuple holding one."""
    from .membership import decided_unhashable

    return decided_unhashable(value)


def _hash_decided(value) -> bool:
    """Members whose hash and equality the floor decides."""
    from .none_value import NoneValue
    from .string_value import StringValue
    from .term_value import TermValue
    from .tuple_value import TupleValue

    if type(value) in (StringValue, TermValue, NoneValue):
        return True
    if type(value) is TupleValue:
        return all(_hash_decided(element) for element in value.elements)
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    return type(value) in (TrueBoolLiteralSugar, FalseBoolLiteralSugar)


def _index_of(elements, needle):
    """Position of the first member equal to ``needle``: int, -1 (none), or None."""
    from .membership import position

    found = position(needle, elements)
    if found is NotImplemented:
        return UNDECIDED
    return found


def finite_members(value):
    """The members ``iter(value)`` yields, when the floor holds them all.

    A container whose contents are not current holds none of them
    (``object_identity.contents_stale``)."""
    from .dict_value import DictValue
    from .list_value import ListValue
    from .object_identity import contents_stale
    from .set_value import SetValue
    from .string_value import StringValue
    from .tuple_value import TupleValue

    if contents_stale(value):
        return None
    if type(value) in (ListValue, TupleValue):
        return tuple(value.elements)
    if type(value) is DictValue:
        return tuple(key for key, _value in value.entries)
    if type(value) is SetValue:
        return tuple(value.elements)
    if type(value) is StringValue and isinstance(value.value, str):
        return tuple(StringValue(char) for char in value.value)
    return None


def _ordered_members(value):
    """Members in iteration order: a set's order is its hash table's, which the
    floor does not decide beyond a single member."""
    from .set_value import SetValue

    members = finite_members(value)
    if type(value) is SetValue and members is not None and len(members) > 1:
        return None
    return members


def _not_iterable(value) -> bool:
    from .none_value import NoneValue
    from .term_value import TermValue

    return type(value) in (TermValue, NoneValue)


def apply(kind, method, receiver, args, site, ctx):
    """``(post-state, result)`` of ``receiver.<method>(*args)``, or None.

    ``ctx`` is the calling statement's context: a store (``__setitem__`` /
    ``__delitem__``) applies under it.

    A mutator with a value (``list.pop``, ``dict.pop``/``popitem``/
    ``setdefault``) on a ground receiver with ground arguments takes its
    value, or its one halt, from the pinned interpreter
    (``container_mutator_result_fold``, #7757); the receiver's post-state is
    this law's.  The law's own read of the member (and its halt) is kept
    only for a receiver or argument known only by its type.

    A receiver whose contents are not current (it arrived by binding,
    ``object_identity.contents_current``) is not read: a method that reads
    its contents (``pop``'s value, ``remove``'s membership, ``setdefault``,
    an index's bound) is UNDECIDED, and the door applies it to an opaque
    post-state (``_opaque_pair``); a contents-free one
    (``CONTENTS_FREE_METHODS``) applies, its post-state not current."""
    from sugar_lift_py_tests.source_call_resolution import (
        container_mutator_result_fold,
    )

    from .object_identity import contents_current

    owner = f"builtins.{kind}.{method}"
    if kind not in ("list", "dict", "set"):
        return UNDECIDED
    if not contents_current(receiver) and method not in CONTENTS_FREE_METHODS[kind]:
        return UNDECIDED
    cited = container_mutator_result_fold(receiver, method, tuple(args), site)
    if cited is not None and cited.halts() == cited.exits:
        # The call raises: its one halt, and no post-state.
        return cited
    if kind == "list":
        decided = _list(method, receiver, args, site, owner, ctx)
    elif kind == "dict":
        decided = _dict(method, receiver, args, site, owner)
    else:
        decided = _set(method, receiver, args, site, owner)
    if decided is UNDECIDED:
        return decided
    value = None if cited is None else cited.completed_value()
    if value is None:
        return decided
    return decided.and_then(lambda pair: _with_value(pair, value))


def _with_value(pair, value):
    """The law's ``(post-state, result)`` with the cited fold's ``value``."""
    from .tuple_value import TupleValue
    from sugar_lift_py_tests.outcome import ExitSet

    if type(pair) is not TupleValue or len(pair.elements) != 2:
        return ExitSet.completed(pair)
    return _pair(pair.elements[0], value)


def _same_object(receiver, contents):
    """The receiver's own object after the call, holding ``contents``: it
    keeps the receiver's ``allocation`` -- current for an object this frame
    made, not for one that arrived by binding -- and its ``arrival``, the
    binding read that names it (``object_identity``)."""
    from dataclasses import replace

    from .dict_value import DictValue

    if type(receiver) is DictValue:
        return replace(receiver, entries=tuple(contents))
    return replace(receiver, elements=tuple(contents))


def _list(method, receiver, args, site, owner, ctx):
    """Each post-state is the receiver's own object after the call
    (``_same_object``)."""
    elements = tuple(receiver.elements)
    if method == "append" and len(args) == 1:
        return _pair(_same_object(receiver, (*elements, args[0])), _none())
    if method in ("extend", "__iadd__") and len(args) == 1:
        if _not_iterable(args[0]):
            return _raise("TypeError", site, owner)
        members = _ordered_members(args[0])
        if members is None:
            return UNDECIDED
        post = _same_object(receiver, (*elements, *members))
        return _pair(post, post if method == "__iadd__" else _none())
    if method == "insert" and len(args) == 2:
        index = _ground_int(args[0])
        if index is None:
            return UNDECIDED
        updated = list(elements)
        updated.insert(index, args[1])
        return _pair(_same_object(receiver, updated), _none())
    if method == "pop" and len(args) <= 1:
        index = -1 if not args else _ground_int(args[0])
        if index is None:
            return UNDECIDED
        size = len(elements)
        if not -size <= index < size:
            return _raise("IndexError", site, owner)
        position = index if index >= 0 else size + index
        return _pair(
            _same_object(receiver, (*elements[:position], *elements[position + 1 :])),
            elements[position],
        )
    if method == "remove" and len(args) == 1:
        position = _index_of(elements, args[0])
        if position is UNDECIDED:
            return UNDECIDED
        if position < 0:
            return _raise("ValueError", site, owner)
        return _pair(
            _same_object(receiver, (*elements[:position], *elements[position + 1 :])),
            _none(),
        )
    if method == "clear" and not args:
        return _pair(_same_object(receiver, ()), _none())
    if method == "reverse" and not args:
        return _pair(_same_object(receiver, reversed(elements)), _none())
    if method == "sort" and not args:
        return _sorted_list(receiver, elements, site, owner)
    if method == "__setitem__" and len(args) == 2:
        return _then_pair(receiver.setitem(args[0], args[1], site, ctx))
    if method == "__delitem__" and len(args) == 1:
        return _then_pair(receiver.delitem(args[0], site, ctx))
    return UNDECIDED


def _sorted_list(receiver, elements, site, owner):
    """``list.sort()``: a homogeneous ground run sorts; mixed str/int is
    TypeError.  The post-state is the receiver's object (``_same_object``)."""
    from .string_value import StringValue
    from .term_value import TermValue

    if all(type(element) is TermValue for element in elements):
        ordered = sorted(elements, key=lambda element: element.value)
    elif all(
        type(element) is StringValue and isinstance(element.value, str)
        for element in elements
    ):
        ordered = sorted(elements, key=lambda element: element.value)
    elif all(type(element) in (TermValue, StringValue) for element in elements):
        return _raise("TypeError", site, owner)
    else:
        return UNDECIDED
    return _pair(_same_object(receiver, ordered), _none())


def _then_pair(outcome):
    """A floor store's outcome as the pair: its post-state and ``None``.

    A store that raises is its halt, handed back unchanged."""
    from sugar_lift_py_tests.outcome import ExitSet

    if not isinstance(outcome, ExitSet):
        return UNDECIDED
    if outcome.halts() == outcome.exits:
        return outcome
    post = outcome.completed_value()
    if post is None or container_kind(post) is None:
        return UNDECIDED
    # Rebuilt through ``sequence`` so the arm's ``owed`` rides onto the pair.
    return outcome.sequence(lambda value: _pair(value, _none()))


def _find_key(entries, key):
    """Position of ``key`` among dict entries: int, -1 (absent), or None."""
    return _index_of(tuple(existing for existing, _value in entries), key)


def _dict(method, receiver, args, site, owner):
    """Each post-state is the receiver's own object (``_same_object``)."""
    entries = tuple(receiver.entries)

    def keyed(key):
        if _unhashable(key):
            return "unhashable"
        if not _hash_decided(key):
            return UNDECIDED
        return _find_key(entries, key)

    if method == "__setitem__" and len(args) == 2:
        position = keyed(args[0])
        if position == "unhashable":
            return _raise("TypeError", site, owner)
        if position is UNDECIDED:
            return UNDECIDED
        return _pair(
            _same_object(receiver, _stored(entries, position, args[0], args[1])),
            _none(),
        )
    if method == "__delitem__" and len(args) == 1:
        position = keyed(args[0])
        if position == "unhashable":
            return _raise("TypeError", site, owner)
        if position is UNDECIDED:
            return UNDECIDED
        if position < 0:
            return _raise("KeyError", site, owner)
        return _pair(
            _same_object(receiver, entries[:position] + entries[position + 1 :]),
            _none(),
        )
    if method == "setdefault" and len(args) in (1, 2):
        default = args[1] if len(args) == 2 else _none()
        position = keyed(args[0])
        if position == "unhashable":
            return _raise("TypeError", site, owner)
        if position is UNDECIDED:
            return UNDECIDED
        if position >= 0:
            return _pair(receiver, entries[position][1])
        return _pair(_same_object(receiver, (*entries, (args[0], default))), default)
    if method == "pop" and len(args) in (1, 2):
        position = keyed(args[0])
        if position == "unhashable":
            return _raise("TypeError", site, owner)
        if position is UNDECIDED:
            return UNDECIDED
        if position < 0:
            if len(args) == 2:
                return _pair(receiver, args[1])
            return _raise("KeyError", site, owner)
        return _pair(
            _same_object(receiver, entries[:position] + entries[position + 1 :]),
            entries[position][1],
        )
    if method == "popitem" and not args:
        if not entries:
            return _raise("KeyError", site, owner)
        from .tuple_value import TupleValue

        key, value = entries[-1]
        return _pair(_same_object(receiver, entries[:-1]), TupleValue((key, value)))
    if method == "clear" and not args:
        return _pair(_same_object(receiver, ()), _none())
    if method in ("update", "__ior__") and len(args) == 1:
        from .dict_value import DictValue
        from .object_identity import contents_stale

        other = args[0]
        if type(other) is not DictValue or contents_stale(other):
            return UNDECIDED
        updated = entries
        for key, value in other.entries:
            if _unhashable(key):
                return _raise("TypeError", site, owner)
            if not _hash_decided(key):
                return UNDECIDED
            position = _find_key(updated, key)
            if position is UNDECIDED:
                return UNDECIDED
            updated = _stored(updated, position, key, value)
        post = _same_object(receiver, updated)
        return _pair(post, post if method == "__ior__" else _none())
    return UNDECIDED


def _stored(entries, position, key, value):
    """Dict entries after ``d[key] = value``: replace in place or append."""
    if position >= 0:
        existing_key = entries[position][0]
        return (*entries[:position], (existing_key, value), *entries[position + 1 :])
    return (*entries, (key, value))


def _set(method, receiver, args, site, owner):
    """Each post-state is the receiver's own object (``_same_object``)."""
    from .set_value import SetValue

    elements = tuple(receiver.elements)

    def member(value):
        if _unhashable(value):
            return "unhashable"
        if not _hash_decided(value):
            return UNDECIDED
        return _index_of(elements, value)

    if method == "add" and len(args) == 1:
        position = member(args[0])
        if position == "unhashable":
            return _raise("TypeError", site, owner)
        if position is UNDECIDED:
            return UNDECIDED
        post = (
            receiver
            if position >= 0
            else _same_object(receiver, (*elements, args[0]))
        )
        return _pair(post, _none())
    if method in ("discard", "remove") and len(args) == 1:
        if type(args[0]) is SetValue:
            # CPython looks a set argument up as a ``frozenset`` of it.
            return UNDECIDED
        position = member(args[0])
        if position == "unhashable":
            return _raise("TypeError", site, owner)
        if position is UNDECIDED:
            return UNDECIDED
        if position < 0:
            if method == "remove":
                return _raise("KeyError", site, owner)
            return _pair(receiver, _none())
        return _pair(
            _same_object(receiver, elements[:position] + elements[position + 1 :]),
            _none(),
        )
    if method == "pop" and not args:
        if not elements:
            return _raise("KeyError", site, owner)
        if len(elements) == 1:
            return _pair(_same_object(receiver, ()), elements[0])
        # Which member ``pop`` returns is hash order: not decided here.
        return UNDECIDED
    if method == "clear" and not args:
        return _pair(_same_object(receiver, ()), _none())
    if method in ("update", "__ior__") and len(args) == 1:
        if method == "__ior__" and type(args[0]) is not SetValue:
            # ``s |= x`` takes a set operand; any other is the operator's
            # dispatch, not ``update``.
            return UNDECIDED
        if _not_iterable(args[0]):
            return _raise("TypeError", site, owner)
        members = finite_members(args[0])
        if members is None:
            return UNDECIDED
        updated = elements
        for candidate in members:
            if _unhashable(candidate):
                return _raise("TypeError", site, owner)
            if not _hash_decided(candidate):
                return UNDECIDED
            position = _index_of(updated, candidate)
            if position is UNDECIDED:
                return UNDECIDED
            if position < 0:
                updated = (*updated, candidate)
        post = _same_object(receiver, updated)
        return _pair(post, post if method == "__ior__" else _none())
    return UNDECIDED
