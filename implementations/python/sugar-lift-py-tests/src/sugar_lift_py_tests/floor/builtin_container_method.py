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

# Methods of each built-in container that change the receiver. A call of one
# of these names on a receiver whose type is not decided may mutate it.
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

ANY_MUTATING_METHOD = frozenset().union(*MUTATING_METHODS.values())


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
    from sugar_lift_py_tests.outcome import Complete

    return Complete(TupleValue((post, result)))


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
    """The members ``iter(value)`` yields, when the floor holds them all."""
    from .dict_value import DictValue
    from .list_value import ListValue
    from .set_value import SetValue
    from .string_value import StringValue
    from .tuple_value import TupleValue

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


def apply(kind, method, receiver, args, site):
    """``(post-state, result)`` of ``receiver.<method>(*args)``, or None."""
    owner = f"builtins.{kind}.{method}"
    if kind == "list":
        return _list(method, receiver, args, site, owner)
    if kind == "dict":
        return _dict(method, receiver, args, site, owner)
    if kind == "set":
        return _set(method, receiver, args, site, owner)
    return UNDECIDED


def _list(method, receiver, args, site, owner):
    from .list_value import ListValue

    elements = tuple(receiver.elements)
    if method == "append" and len(args) == 1:
        return _pair(ListValue((*elements, args[0])), _none())
    if method in ("extend", "__iadd__") and len(args) == 1:
        if _not_iterable(args[0]):
            return _raise("TypeError", site, owner)
        members = _ordered_members(args[0])
        if members is None:
            return UNDECIDED
        post = ListValue((*elements, *members))
        return _pair(post, post if method == "__iadd__" else _none())
    if method == "insert" and len(args) == 2:
        index = _ground_int(args[0])
        if index is None:
            return UNDECIDED
        updated = list(elements)
        updated.insert(index, args[1])
        return _pair(ListValue(tuple(updated)), _none())
    if method == "pop" and len(args) <= 1:
        index = -1 if not args else _ground_int(args[0])
        if index is None:
            return UNDECIDED
        size = len(elements)
        if not -size <= index < size:
            return _raise("IndexError", site, owner)
        position = index if index >= 0 else size + index
        return _pair(
            ListValue((*elements[:position], *elements[position + 1 :])),
            elements[position],
        )
    if method == "remove" and len(args) == 1:
        position = _index_of(elements, args[0])
        if position is UNDECIDED:
            return UNDECIDED
        if position < 0:
            return _raise("ValueError", site, owner)
        return _pair(
            ListValue((*elements[:position], *elements[position + 1 :])), _none()
        )
    if method == "clear" and not args:
        return _pair(ListValue(()), _none())
    if method == "reverse" and not args:
        return _pair(ListValue(tuple(reversed(elements))), _none())
    if method == "sort" and not args:
        return _sorted_list(elements, site, owner)
    if method == "__setitem__" and len(args) == 2:
        return _then_pair(receiver.setitem(args[0], args[1], site))
    if method == "__delitem__" and len(args) == 1:
        return _then_pair(receiver.delitem(args[0], site))
    return UNDECIDED


def _sorted_list(elements, site, owner):
    """``list.sort()``: a homogeneous ground run sorts; mixed str/int is TypeError."""
    from .list_value import ListValue
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
    return _pair(ListValue(tuple(ordered)), _none())


def _then_pair(outcome):
    """A floor store's outcome as the pair: its post-state and ``None``.

    A store that raises is its halt, handed back unchanged."""
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    if isinstance(outcome, Incomplete):
        return outcome
    if not isinstance(outcome, Complete):
        return UNDECIDED
    if container_kind(outcome.value) is None:
        return UNDECIDED
    return _pair(outcome.value, _none())


def _find_key(entries, key):
    """Position of ``key`` among dict entries: int, -1 (absent), or None."""
    return _index_of(tuple(existing for existing, _value in entries), key)


def _dict(method, receiver, args, site, owner):
    from .dict_value import DictValue

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
        return _pair(DictValue(_stored(entries, position, args[0], args[1])), _none())
    if method == "__delitem__" and len(args) == 1:
        position = keyed(args[0])
        if position == "unhashable":
            return _raise("TypeError", site, owner)
        if position is UNDECIDED:
            return UNDECIDED
        if position < 0:
            return _raise("KeyError", site, owner)
        return _pair(DictValue(entries[:position] + entries[position + 1 :]), _none())
    if method == "setdefault" and len(args) in (1, 2):
        default = args[1] if len(args) == 2 else _none()
        position = keyed(args[0])
        if position == "unhashable":
            return _raise("TypeError", site, owner)
        if position is UNDECIDED:
            return UNDECIDED
        if position >= 0:
            return _pair(receiver, entries[position][1])
        return _pair(DictValue((*entries, (args[0], default))), default)
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
            DictValue(entries[:position] + entries[position + 1 :]),
            entries[position][1],
        )
    if method == "popitem" and not args:
        if not entries:
            return _raise("KeyError", site, owner)
        from .tuple_value import TupleValue

        key, value = entries[-1]
        return _pair(DictValue(entries[:-1]), TupleValue((key, value)))
    if method == "clear" and not args:
        return _pair(DictValue(()), _none())
    if method in ("update", "__ior__") and len(args) == 1:
        other = args[0]
        if type(other) is not DictValue:
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
        post = DictValue(updated)
        return _pair(post, post if method == "__ior__" else _none())
    return UNDECIDED


def _stored(entries, position, key, value):
    """Dict entries after ``d[key] = value``: replace in place or append."""
    if position >= 0:
        existing_key = entries[position][0]
        return (*entries[:position], (existing_key, value), *entries[position + 1 :])
    return (*entries, (key, value))


def _set(method, receiver, args, site, owner):
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
        post = receiver if position >= 0 else SetValue((*elements, args[0]))
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
        return _pair(SetValue(elements[:position] + elements[position + 1 :]), _none())
    if method == "pop" and not args:
        if not elements:
            return _raise("KeyError", site, owner)
        if len(elements) == 1:
            return _pair(SetValue(()), elements[0])
        # Which member ``pop`` returns is hash order: not decided here.
        return UNDECIDED
    if method == "clear" and not args:
        return _pair(SetValue(()), _none())
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
        post = SetValue(updated)
        return _pair(post, post if method == "__ior__" else _none())
    return UNDECIDED
