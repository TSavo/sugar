"""CPython's container membership: ``x in c`` and the key/member lookup behind it.

One law, shared by ``list``/``tuple``/``set``/``dict`` membership, a dict's
key lookup (``d[k]``, ``d[k] = v``, ``del d[k]``, ``d | e``) and the cited
mutating methods (``floor/builtin_container_method``):

- **Equality.** A member matches when ``x is e or x == e``
  (``PyObject_RichCompareBool``, which every container lookup uses).
  ``bool`` is an ``int`` subclass, so ``True == 1``, ``False == 0`` and
  ``1.0 == 1``; a tuple compares elementwise and is unequal at its first
  unequal element.
- **Identity.** ``float('nan') == float('nan')`` is False, but a NaN matches
  itself by identity, and the floor does not carry object identity: two NaN
  members are undecided, never False.
- **Hash.** ``set``/``dict`` hash the needle first: a decided unhashable needle
  (a list, dict, set, or a tuple holding one) raises ``TypeError`` before any
  comparison, and a needle whose hash the floor does not decide may raise
  there. Equal decided builtin values hash equal, so equality then decides.
- **Classes and functions.** A class or a function is a member like any
  object: ``type(x) in (int, float)``, ``cls in (A, B)``,
  ``handler in handlers``. Where the floor has no value equality for a pair
  (``member_equal`` is ``NotImplemented``), ``==`` is answered by identity
  where Python answers it so (``object_identity.equality_by_identity``: a
  class whose metaclass is decided to be ``type``), else it is undecided.
  Never a construction panic.
- **Undecided.** A list or tuple compares its members in order, so it
  matches at the first decided match and is undecided at the first member
  whose equality is not decided before that; a set or dict probes by hash,
  so any undecided member (or needle hash) leaves it undecided. Undecided
  membership is the floor's one undecided form
  (``FloorValue.undecided_contains``): it completes with the keyed
  ``py.in`` only under its completes atom and halts undetermined under the
  complement, owed either way -- never a bare predicate, never False
  (#7757 H10).
"""

from __future__ import annotations


def _is_nan(value) -> bool:
    return isinstance(value, float) and value != value


def member_equal(left, right):
    """``left is right or left == right``: True, False, None (undecided), or
    NotImplemented (a pair the floor has no equality for)."""
    from sugar_lift_py_tests.floor.bytes_value import BytesValue
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.set_value import _denotes_a_value
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    if type(left) is SymbolicValue or type(right) is SymbolicValue:
        return None
    bools = {TrueBoolLiteralSugar: 1, FalseBoolLiteralSugar: 0}
    # ``True == 1`` and ``False == 0.0``: a bool compares as its int.
    left_number = bools.get(type(left), getattr(left, "value", None))
    right_number = bools.get(type(right), getattr(right, "value", None))
    numeric = (TermValue, *bools)
    if type(left) in numeric and type(right) in numeric:
        if _is_nan(left_number) and _is_nan(right_number):
            # NaN != NaN, yet a NaN is itself: identity decides, and the floor
            # does not carry it.
            return None
        return left_number == right_number
    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.set_value import SetValue

    supported = (
        TermValue,
        StringValue,
        BytesValue,
        NoneValue,
        *bools,
        ListValue,
        TupleValue,
        SetValue,
        DictValue,
    )
    if type(left) in supported and type(right) in supported:
        if type(left) in (StringValue, BytesValue) and type(left) is type(right):
            return left.value == right.value
        # ``None`` is a singleton: ``None is None``, so it is its own member.
        if type(left) is NoneValue and type(right) is NoneValue:
            return True
        # Nested sequence membership: ``[1] in [[1], [2]]`` is ground list
        # equality on each element -- of contents that are current
        # (``object_identity.contents_stale``); stale ones are not read.
        if type(left) in (ListValue, TupleValue) and type(left) is type(right):
            from sugar_lift_py_tests.floor.object_identity import contents_stale

            if contents_stale(left) or contents_stale(right):
                return None
            return sequence_equal(left.elements, right.elements)
        if type(left) in (SetValue, DictValue) and type(left) is type(right):
            # Order-free equality the floor does not decide here.
            return None
        # Two decided builtin values of different types (bools and numbers
        # were compared above): ``None == 0``, ``[1] == (1,)``, ``'1' == 1``
        # are all False.
        return False
    # Only a decided builtin on BOTH sides decides inequality: ``None`` or a
    # list against a call's result is undecided, never False.  A call's
    # result IS a value of undecided identity, so the answer is ``None``.
    # A side that testifies to no value (``FloorValue.denotes_a_value``,
    # testimony each floor states about ITSELF and which defaults to no: a
    # class, a function, a bound method) has no value equality here:
    # ``NotImplemented``.  Membership then asks identity
    # (``membership``'s ``_member_decision``), never refuses.
    if _denotes_a_value(left, supported) and _denotes_a_value(right, supported):
        return None
    return NotImplemented


def sequence_equal(left_elements, right_elements):
    """Elementwise ``==`` of two sequences: unequal at the first unequal pair."""
    if len(left_elements) != len(right_elements):
        return False
    decisions = tuple(
        member_equal(left, right) for left, right in zip(left_elements, right_elements)
    )
    if any(decision is False for decision in decisions):
        return False
    if any(decision is None for decision in decisions):
        return None
    if any(decision is NotImplemented for decision in decisions):
        return NotImplemented
    return True


def decided_unhashable(value) -> bool:
    """A needle whose ``hash`` decidedly raises: a list/dict/set, or a tuple
    holding one."""
    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.set_value import SetValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    if type(value) in (ListValue, DictValue, SetValue):
        return True
    if type(value) is TupleValue:
        return any(decided_unhashable(element) for element in value.elements)
    return False


def decided_distinct(members) -> bool:
    """Every pair of ``members`` decidedly unequal under ``is``-or-``==``: the
    count CPython's hash table keeps is then ``len(members)``.  A pair the
    floor does not decide leaves the count undecided -- a construction that
    could not collapse it must not count it as two."""
    for index, left in enumerate(members):
        for right in members[index + 1 :]:
            if member_equal(left, right) is not False:
                return False
    return True


def position(needle, members):
    """Index of the first member matching ``needle``: int, -1 (none), None
    (an earlier member's equality is undecided), or NotImplemented."""
    for index, member in enumerate(members):
        decision = member_equal(needle, member)
        if decision is True:
            return index
        if decision is None or decision is NotImplemented:
            return decision
    return -1


def membership(container, item, members, *, kind, hashed, site):
    """``item in container`` over its ``members``: the ExitSet.

    Decided True or False where every comparison it makes is decided; else
    the container's undecided membership (``FloorValue.undecided_contains``),
    two-faced and owed.  A list or tuple (``hashed`` False) compares in
    order: it matches at the first decided match, and is undecided at the
    first undecided member before one.  A set or dict (``hashed``) hashes the
    needle and probes by hash, so a needle whose hash is not decided, or any
    undecided member, leaves it undecided.  A container whose contents are
    not current (``object_identity.contents_stale``) is not read: the test is
    its undecided membership."""
    from sugar_lift_py_tests.floor.object_identity import contents_stale
    from sugar_lift_py_tests.floor.set_value import _bool_result

    owner = f"python.{kind}.contains"
    if hashed and decided_unhashable(item):
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner=owner,
        )
    if contents_stale(container):
        return container.undecided_contains(item, site, owner=owner)
    if hashed:
        if not _needle_hash_decided(item):
            return container.undecided_contains(item, site, owner=owner)
        decisions = tuple(_member_decision(item, member, site) for member in members)
        if any(decision is None for decision in decisions):
            return container.undecided_contains(item, site, owner=owner)
        return _bool_result(any(decisions), site)
    for member in members:
        decision = _member_decision(item, member, site)
        if decision is None:
            return container.undecided_contains(item, site, owner=owner)
        if decision:
            return _bool_result(True, site)
    return _bool_result(False, site)


def _member_decision(item, member, site):
    """``item is member or item == member``: True, False, or None
    (undecided).  Where the floor has no value equality for the pair
    (``member_equal`` is ``NotImplemented``: a class, a function, a bound
    method), ``==`` is identity where Python answers it so -- the one rule
    ``==`` already uses (``object_identity.equality_by_identity``) -- else
    undecided."""
    decision = member_equal(item, member)
    if decision is not NotImplemented:
        return decision
    from sugar_lift_py_tests.floor.object_identity import equality_by_identity
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        plain_completed_value,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    answered = equality_by_identity(item, member, site)
    if answered is None:
        return None
    value = plain_completed_value(answered)
    if type(value) is TrueBoolLiteralSugar:
        return True
    if type(value) is FalseBoolLiteralSugar:
        return False
    return None


def _needle_hash_decided(item) -> bool:
    """``hash(item)`` is CPython's own and never raises: a decided hashable
    builtin (``builtin_container_method._hash_decided``, or ``bytes``) or a
    class whose metaclass is decided to be ``type`` (``type.__hash__`` is its
    identity)."""
    from sugar_lift_py_tests.floor.builtin_container_method import _hash_decided
    from sugar_lift_py_tests.floor.bytes_value import BytesValue
    from sugar_lift_py_tests.floor.object_identity import _type_class

    return type(item) is BytesValue or _hash_decided(item) or _type_class(item)
