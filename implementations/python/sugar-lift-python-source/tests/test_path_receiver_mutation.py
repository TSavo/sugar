"""A mutating call through a path changes the object the path reaches.

``c.items.append(1); return c.items`` lifted as returning ``[]``, and so did
``d['k'].append(1); return d['k']`` read through an earlier ``a = d['k']``: a
receiver reached through an attribute or subscript was never the receiver of
the cited store (#7603 rebinds names only), so the object stayed as it was --
a false claim.

The receiver is the object the path evaluates to. The call is evaluated once,
at the statement: a decided list/dict/set receiver takes CPython's documented
mutation, any other receiver the ordinary call. Every name bound to the root
is rebound to the root after the call -- the path's member replaced by the
post-state when every step is a plain field or a decided item and nothing else
in the root can be that object, otherwise an unknown minted at the call. A
name bound to the same object (the same path, or the node a display holds
there) sees the post-state; any other name that may share the root's objects
is unknown afterwards. Never the pre-call contents.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import (
    DictValue,
    ListValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)

from frame_fresh import FRAME_FRESH, fresh
from test_assignment_evaluates_rhs import _rows
from test_builtin_container_mutation import _only_return, _returns


def _ints(*values):
    return tuple(TermValue(value) for value in values)


def _unknown_after_call(value):
    return (
        type(value) is SymbolicValue
        and value.term.name == "python:receiver_after_call"
    )


def test_an_attribute_receiver_append_is_seen_by_the_attribute_read(tmp_path):
    source = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self.items = []\n"
        "def f():\n"
        "    c = C()\n"
        "    c.items.append(1)\n"
        "    return c.items\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1))


def test_a_subscript_receiver_append_is_seen_through_the_dict(tmp_path):
    source = "def f():\n    d = {'k': []}\n    d['k'].append(1)\n    return d\n"
    assert _only_return(tmp_path, source) == fresh(
        DictValue, ((StringValue("k"), fresh(ListValue, _ints(1))),)
    )


def test_a_name_bound_to_the_same_path_sees_the_append(tmp_path):
    source = (
        "def f():\n"
        "    d = {'k': [], 'j': 1}\n"
        "    a = d['k']\n"
        "    d['k'].append(1)\n"
        "    return (a, d)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue(
        (
            fresh(ListValue, _ints(1)),
            fresh(
                DictValue,
                (
                    (StringValue("k"), fresh(ListValue, _ints(1))),
                    (StringValue("j"), TermValue(1)),
                ),
            ),
        )
    )


def test_a_list_held_twice_by_the_root_leaves_the_root_unknown(tmp_path):
    source = (
        "def f():\n"
        "    L = []\n"
        "    d = {'k': L, 'j': L}\n"
        "    d['k'].append(1)\n"
        "    return (L, d)\n"
    )
    value = _only_return(tmp_path, source)
    first, second = value.elements
    # ``L`` is the node the display holds at 'k': the object itself.
    assert first == fresh(ListValue, _ints(1))
    # 'j' holds that same object; a one-member update would claim it stayed [].
    assert _unknown_after_call(second)


def test_an_object_whose_fields_may_alias_is_unknown_after(tmp_path):
    source = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self.items = []\n"
        "        self.view = self.items\n"
        "def f():\n"
        "    c = C()\n"
        "    c.items.append(1)\n"
        "    return c\n"
    )
    assert _unknown_after_call(_only_return(tmp_path, source))


def test_repeated_calls_through_one_path_thread_one_object(tmp_path):
    source = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self.items = []\n"
        "        self.n = 0\n"
        "def f():\n"
        "    c = C()\n"
        "    a = c.items\n"
        "    c.items.append(1)\n"
        "    c.items.append(2)\n"
        "    x = c.items.pop()\n"
        "    return (a, c.items, x, c.n)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue(
        (
            fresh(ListValue, _ints(1)),
            fresh(ListValue, _ints(1)),
            TermValue(2),
            TermValue(0),
        )
    )


def test_a_nested_list_element_append(tmp_path):
    source = (
        "def f():\n"
        "    r = [[]]\n"
        "    s = r[0]\n"
        "    r[0].append(1)\n"
        "    return (s, r)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue(
        (fresh(ListValue, _ints(1)), fresh(ListValue, (fresh(ListValue, _ints(1)),)))
    )


def test_a_path_pop_from_an_empty_list_is_index_error_inside_the_try(tmp_path):
    source = (
        "def f():\n"
        "    d = {'k': []}\n"
        "    try:\n"
        "        d['k'].pop()\n"
        "    except IndexError:\n"
        "        return 'caught'\n"
        "    return 'no'\n"
    )
    assert _only_return(tmp_path, source) == StringValue("caught")


def test_an_unrolled_loop_appends_through_the_path(tmp_path):
    source = (
        "def f():\n"
        "    d = {'k': []}\n"
        "    for i in range(2):\n"
        "        d['k'].append(i)\n"
        "    return d\n"
    )
    assert _only_return(tmp_path, source) == fresh(
        DictValue, ((StringValue("k"), fresh(ListValue, _ints(0, 1))),)
    )


def test_a_symbolic_loop_leaves_the_root_unknown(tmp_path):
    source = (
        "def f(xs):\n"
        "    d = {'k': []}\n"
        "    for x in xs:\n"
        "        d['k'].append(x)\n"
        "    return d\n"
    )
    assert _unknown_after_call(_only_return(tmp_path, source))


def test_a_source_method_through_a_path_never_keeps_the_old_root(tmp_path):
    # ``c.h.add(1)`` runs ``H.add``, which appends to ``c.h.s``; the lift used
    # to answer ``c.h.s`` as the pre-call ``[]``. The root is now unknown
    # after the call, so its later reads are refusals, never ``[]``.
    source = (
        "class H:\n"
        "    def __init__(self):\n"
        "        self.s = []\n"
        "    def add(self, x):\n"
        "        self.s.append(x)\n"
        "class C:\n"
        "    def __init__(self):\n"
        "        self.h = H()\n"
        "def f():\n"
        "    c = C()\n"
        "    c.h.add(1)\n"
        "    return c\n"
    )
    assert _unknown_after_call(_only_return(tmp_path, source))


# -- A name bound to a value the source does not type (#7757) ---------------
#
# ``parts = 'a b'.split()`` binds ``parts`` to the lifter's ``ListValue``, but
# the right-hand side is not a list display, so the tree never decided the
# receiver: the append ran on the list and ``parts`` was rebound to an unknown
# after it.  The path door with no steps asks the value the binding holds, so
# a list display and a folded ``str.split`` are one case.


def _strings(*values):
    return tuple(StringValue(value) for value in values)


def test_append_to_a_ground_split_is_read_through_the_name(tmp_path):
    source = (
        "def f():\n"
        "    parts = 'a b'.split()\n"
        "    parts.append('c')\n"
        "    return parts\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _strings("a", "b", "c"))


def test_a_ground_split_and_a_display_append_alike(tmp_path):
    split = (
        "def f():\n"
        "    parts = 'a b'.split()\n"
        "    alias = parts\n"
        "    parts.append('c')\n"
        "    return (alias, parts)\n"
    )
    display = split.replace("'a b'.split()", "['a', 'b']")
    expected = TupleValue(
        (
            fresh(ListValue, _strings("a", "b", "c")),
            fresh(ListValue, _strings("a", "b", "c")),
        )
    )
    assert _only_return(tmp_path / "split", split) == expected
    assert _only_return(tmp_path / "display", display) == expected


def test_a_pop_from_a_ground_split_binds_the_element_and_the_rest(tmp_path):
    source = (
        "def f():\n"
        "    parts = 'a b'.split()\n"
        "    x = parts.pop()\n"
        "    return (x, parts)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue(
        (StringValue("b"), fresh(ListValue, _strings("a")))
    )


def test_a_value_holding_a_ground_split_is_unknown_after_its_append(tmp_path):
    # Discriminating: the object's own name reads the post-state; a value that
    # merely holds it is unknown, never the pre-call ``[['a', 'b']]``.
    source = (
        "def f():\n"
        "    parts = 'a b'.split()\n"
        "    outer = [parts]\n"
        "    parts.append('c')\n"
        "    return outer\n"
    )
    value = _only_return(tmp_path, source)
    assert value != fresh(ListValue, (fresh(ListValue, _strings("a", "b")),))
    assert _unknown_after_call(value)


# -- One door for every mutation on a name (#7757) ---------------------------
#
# ``r[k] = v``, ``del r[k]`` and ``r += x`` take the same door a method
# mutator does, whatever ``r`` was given: the value ``r`` holds at reduce
# decides, never the spelling of its right-hand side.


def test_an_item_store_on_a_ground_split_is_read_through_the_name(tmp_path):
    source = (
        "def f():\n"
        "    r = 'a b'.split()\n"
        "    r[0] = 'z'\n"
        "    return r\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _strings("z", "b"))


def test_an_item_delete_on_a_ground_split_is_read_through_the_name(tmp_path):
    source = (
        "def f():\n"
        "    r = 'a b'.split()\n"
        "    del r[0]\n"
        "    return r\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _strings("b"))


def test_an_augmented_add_on_a_ground_split_is_read_through_the_name(tmp_path):
    source = (
        "def f():\n"
        "    r = 'a b'.split()\n"
        "    r += ['c']\n"
        "    return r\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _strings("a", "b", "c"))


def test_every_mutation_of_a_ground_split_is_seen_through_an_alias(tmp_path):
    # Discriminating: the alias names the same object, so it reads every
    # mutation's post-state, never the pre-call ``['a', 'b']`` (the old
    # syntax door left a split's alias stale for ``[k] =``/``del``/``+=``).
    source = (
        "def f():\n"
        "    r = 'a b'.split()\n"
        "    alias = r\n"
        "    r[0] = 'z'\n"
        "    del r[1]\n"
        "    r += ['c']\n"
        "    return (alias, r)\n"
    )
    expected = fresh(ListValue, _strings("z", "c"))
    assert _only_return(tmp_path, source) == TupleValue((expected, expected))


def test_an_augmented_add_on_an_int_keeps_its_aliases(tmp_path):
    # ``n += 1`` takes the same door; an int is not changed in place, so the
    # alias keeps its own value and ``n`` reads the in-place result.
    source = (
        "def f():\n"
        "    n = 1\n"
        "    m = n\n"
        "    n += 1\n"
        "    n += 1\n"
        "    return (m, n)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue((TermValue(1), TermValue(3)))


def test_a_parameter_reads_the_post_state_of_its_append(tmp_path):
    # A formal takes the one door too: once the caller's list is supplied,
    # ``xs`` reads the object after the call (unknown here: the call ran on
    # the formal), never the pre-call ``[]``.
    from test_formal_method_call_defers import _carrier, _discharge

    source = "def f(xs):\n    xs.append(1)\n    return xs\n"
    exits = _discharge(_carrier(tmp_path, source), fresh(ListValue, ()))
    returns = [payload for kind, payload, _ in _rows(exits) if kind == "return"]
    assert returns
    assert fresh(ListValue, ()) not in returns
    assert all(
        _unknown_after_call(value) and value.term.args[1].value == "xs"
        for value in returns
    )


# -- d.setdefault(k, v).<mutator>(...) takes the one door (#7757) ------------
#
# The setdefault is the name's own operation; its value -- the object ``d[k]``
# holds after it -- is the receiver of the mutator, a path from ``d`` through
# the item ``k``.  It had a door of its own that rebound ``d`` alone: an alias
# of ``d``, or a name bound to the list at ``d[k]``, kept the pre-call value.


def test_a_setdefault_append_inserts_the_default_and_every_alias_sees_it(tmp_path):
    source = (
        "def f():\n"
        "    d = {}\n"
        "    e = d\n"
        "    d.setdefault('k', []).append('x')\n"
        "    return (e, d['k'])\n"
    )
    after = fresh(ListValue, _strings("x"))
    assert _only_return(tmp_path, source) == TupleValue(
        (fresh(DictValue, ((StringValue("k"), after),)), after)
    )


def test_a_setdefault_append_on_an_existing_key_changes_the_held_list(tmp_path):
    # Discriminating: ``L`` is the object at ``d['x']``; the old door rebound
    # ``d`` only, so ``L`` read the pre-call ``[1]``.  The default ``[9]`` is
    # never stored.
    source = (
        "def f():\n"
        "    L = [1]\n"
        "    d = {'x': L}\n"
        "    d.setdefault('x', [9]).append(2)\n"
        "    return (L, d['x'])\n"
    )
    after = fresh(ListValue, _ints(1, 2))
    assert _only_return(tmp_path, source) == TupleValue((after, after))


def test_repeated_setdefault_appends_thread_one_dict(tmp_path):
    source = (
        "def f():\n"
        "    d = {}\n"
        "    e = d\n"
        "    d.setdefault('k', []).append(1)\n"
        "    d.setdefault('k', []).append(2)\n"
        "    return e\n"
    )
    assert _only_return(tmp_path, source) == fresh(
        DictValue, ((StringValue("k"), fresh(ListValue, _ints(1, 2))),)
    )


def test_a_setdefault_default_held_by_another_name_is_never_stale(tmp_path):
    # The key is no literal, so the source does not say which member the
    # setdefault names: ``L`` may become ``d[k]`` and be appended to.  It is
    # unknown after the statement, never the pre-call ``[]``.
    source = (
        "def f():\n"
        "    k = 'a b'.split()[0]\n"
        "    L = []\n"
        "    d = {'j': []}\n"
        "    d.setdefault(k, L).append(1)\n"
        "    return L\n"
    )
    value = _only_return(tmp_path, source)
    assert value != fresh(ListValue, ())
    assert _unknown_after_call(value)


# -- Exposure is one rule for every name a call can reach (#7757) -----------
#
# A parameter and an instance of a source class handed to an opaque call were
# never rebound: their later reads (and an alias's) were the pre-call value.
# Every name bound to the object is now rebound to its value after the call,
# which the value decides at reduce (``ReceiverAfterCall``).


def _substituted_return_reads(source):
    """The reads ``f``'s final ``return (...)`` makes, after substitution, as
    the nodes the objects they denote are."""
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.container_mutation import _identity
    from sugar_source_tree.nodes import FunctionDef, Return
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "exposure_fixture.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "f"
    )
    substituted = function.substitute({})
    returned = next(
        statement
        for statement in reversed(substituted.body)
        if isinstance(statement, Return)
    )
    return [_identity(read) for read in returned.value.elts]


def test_a_parameter_handed_to_an_opaque_call_is_rebound_with_its_alias():
    source = (
        "def f(xs, g):\n"
        "    alias = xs\n"
        "    g(xs)\n"
        "    return (alias, xs)\n"
    )
    reads = _substituted_return_reads(source)
    assert [read.kind for read in reads] == ["ReceiverAfterCall"] * 2


def test_a_source_instance_handed_to_an_opaque_call_is_rebound_with_its_alias():
    # A class attribute keeps ``C()`` from being an object place: the
    # instance is the call's value, which the exposure rule used to skip.
    source = (
        "class C:\n"
        "    tag = 'c'\n"
        "    def __init__(self):\n"
        "        self.items = [5]\n"
        "def f(g):\n"
        "    c = C()\n"
        "    alias = c\n"
        "    g(c)\n"
        "    return (alias, c)\n"
    )
    reads = _substituted_return_reads(source)
    assert [read.kind for read in reads] == ["ReceiverAfterCall"] * 2


def test_a_source_object_an_opaque_call_reaches_may_have_changed():
    from sugar_lift_py_tests.floor.object_field import ObjectField
    from sugar_lift_py_tests.floor.object_value import ObjectValue
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _may_change

    instance = ObjectValue(
        "C",
        (ObjectField("items", fresh(ListValue, _ints(5))),),
        allocation=FRAME_FRESH,
    )
    # Handed to the call, or the receiver of a method of its own.
    assert _may_change(instance, "", False, False)
    assert _may_change(instance, "add", False, False)
    # An immutable value is still kept.
    assert not _may_change(StringValue("s"), "", False, False)


# -- Stores through a path, chained and unpacked, take the door (#7757) -----
#
# ``a.b[k] = v`` and ``a[i][j] = v`` were ordinary stores: the root, and a name
# bound to the object the path reaches, kept the pre-store value.  A chain's
# and an unpack's store targets are each that same single-target store.


def test_an_item_store_through_a_subscript_path_is_seen_by_every_alias(tmp_path):
    source = (
        "def f():\n"
        "    d = {'k': [0, 1]}\n"
        "    e = d\n"
        "    a = d['k']\n"
        "    d['k'][0] = 9\n"
        "    return (a, e)\n"
    )
    after = fresh(ListValue, _ints(9, 1))
    assert _only_return(tmp_path, source) == TupleValue(
        (after, fresh(DictValue, ((StringValue("k"), after),)))
    )


def test_an_item_store_through_a_nested_list_is_seen_by_the_inner_alias(tmp_path):
    source = (
        "def f():\n"
        "    r = [[0], [1]]\n"
        "    s = r[0]\n"
        "    r[0][0] = 5\n"
        "    return (s, r)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue(
        (
            fresh(ListValue, _ints(5)),
            fresh(
                ListValue, (fresh(ListValue, _ints(5)), fresh(ListValue, _ints(1)))
            ),
        )
    )


def test_an_item_store_through_an_attribute_path_is_seen_by_the_alias(tmp_path):
    source = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self.items = [0]\n"
        "        self.n = 0\n"
        "def f():\n"
        "    c = C()\n"
        "    a = c.items\n"
        "    c.items[0] = 7\n"
        "    return (a, c.items, c.n)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue(
        (fresh(ListValue, _ints(7)), fresh(ListValue, _ints(7)), TermValue(0))
    )


def test_an_item_delete_through_a_path_is_seen_by_the_alias(tmp_path):
    source = (
        "def f():\n"
        "    d = {'k': [0, 1]}\n"
        "    a = d['k']\n"
        "    del d['k'][0]\n"
        "    return (a, d)\n"
    )
    after = fresh(ListValue, _ints(1))
    assert _only_return(tmp_path, source) == TupleValue(
        (after, fresh(DictValue, ((StringValue("k"), after),)))
    )


def test_a_chained_store_through_a_path_is_seen_by_the_alias(tmp_path):
    source = (
        "def f():\n"
        "    d = {'k': [0]}\n"
        "    a = d['k']\n"
        "    x = d['k'][0] = 5\n"
        "    return (a, d, x)\n"
    )
    after = fresh(ListValue, _ints(5))
    assert _only_return(tmp_path, source) == TupleValue(
        (after, fresh(DictValue, ((StringValue("k"), after),)), TermValue(5))
    )


def test_a_chained_name_binding_is_one_object_for_the_door(tmp_path):
    # ``a = b = []`` binds two names to one list: a mutation through either
    # is read through both.
    source = (
        "def f():\n"
        "    a = b = []\n"
        "    a.append(1)\n"
        "    b[0] = 2\n"
        "    return (a, b)\n"
    )
    after = fresh(ListValue, _ints(2))
    assert _only_return(tmp_path, source) == TupleValue((after, after))


def test_unpacked_store_targets_are_seen_by_the_alias(tmp_path):
    source = (
        "def f():\n"
        "    r = [0, 0]\n"
        "    alias = r\n"
        "    r[0], r[1] = 1, 2\n"
        "    return alias\n"
    )
    assert _only_return(tmp_path, source) == fresh(ListValue, _ints(1, 2))


def test_an_unpacked_store_through_a_path_is_seen_by_the_alias(tmp_path):
    source = (
        "def f():\n"
        "    d = {'k': [0]}\n"
        "    a = d['k']\n"
        "    d['k'][0], n = 1, 2\n"
        "    return (a, d, n)\n"
    )
    after = fresh(ListValue, _ints(1))
    assert _only_return(tmp_path, source) == TupleValue(
        (after, fresh(DictValue, ((StringValue("k"), after),)), TermValue(2))
    )


def test_unpacked_names_bound_to_containers_are_their_objects(tmp_path):
    # ``a, b = x, y`` binds ``a`` to ``x``'s list: a mutation through ``a``
    # is read through ``x``.
    source = (
        "def f():\n"
        "    x = [0]\n"
        "    y = [1]\n"
        "    a, b = x, y\n"
        "    a.append(2)\n"
        "    b[0] = 3\n"
        "    return (x, y)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue(
        (fresh(ListValue, _ints(0, 2)), fresh(ListValue, _ints(3)))
    )


# -- The leftovers of #8119 take the one door (#7757) ------------------------
#
# ``d['k'][0] += 1`` was an ordinary augmented store: the root and a name
# bound to the object the path reaches kept the pre-store value.  ``x =
# d.setdefault(k, v).pop()`` was an ordinary call.  ``a, b = pair`` (no ground
# display) bound ``a`` to a reference that denoted no object: every read was
# its own object, so an alias of ``a`` never saw a mutation through ``a``.


def test_an_augmented_item_store_through_a_path_is_seen_by_every_alias(tmp_path):
    source = (
        "def f():\n"
        "    d = {'k': [1, 2]}\n"
        "    e = d\n"
        "    a = d['k']\n"
        "    d['k'][0] += 10\n"
        "    return (a, e)\n"
    )
    after = fresh(ListValue, _ints(11, 2))
    assert _only_return(tmp_path, source) == TupleValue(
        (after, fresh(DictValue, ((StringValue("k"), after),)))
    )


def test_an_augmented_item_store_on_a_name_is_seen_through_an_alias(tmp_path):
    source = (
        "def f():\n"
        "    r = 'a b'.split()\n"
        "    alias = r\n"
        "    r[0] += 'z'\n"
        "    return (alias, r)\n"
    )
    expected = fresh(ListValue, _strings("az", "b"))
    assert _only_return(tmp_path, source) == TupleValue((expected, expected))


def test_an_augmented_list_item_held_by_another_name_is_never_stale(tmp_path):
    # ``L`` is the list at ``d['k'][0]``; ``+= [2]`` extends it in place.  The
    # store names ``d['k']``, so ``L`` is unknown after it, never the
    # pre-store ``[1]``.
    source = (
        "def f():\n"
        "    d = {'k': [[1]]}\n"
        "    L = d['k'][0]\n"
        "    d['k'][0] += [2]\n"
        "    return L\n"
    )
    value = _only_return(tmp_path, source)
    assert value != fresh(ListValue, _ints(1))
    assert _unknown_after_call(value)


def test_a_bound_setdefault_pop_changes_the_held_list_and_every_alias(tmp_path):
    # Discriminating: ``L`` is the object at ``d['x']`` and ``e`` names ``d``;
    # the ordinary call left both reading the pre-call ``[1, 2]``.
    source = (
        "def f():\n"
        "    L = [1, 2]\n"
        "    d = {'x': L}\n"
        "    e = d\n"
        "    x = d.setdefault('x', []).pop()\n"
        "    return (x, L, e)\n"
    )
    after = fresh(ListValue, _ints(1))
    assert _only_return(tmp_path, source) == TupleValue(
        (TermValue(2), after, fresh(DictValue, ((StringValue("x"), after),)))
    )


def test_a_bound_setdefault_pop_on_a_missing_key_pops_the_default(tmp_path):
    source = (
        "def f():\n"
        "    d = {}\n"
        "    e = d\n"
        "    x = d.setdefault('k', [5]).pop()\n"
        "    return (x, e)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue(
        (
            TermValue(5),
            fresh(DictValue, ((StringValue("k"), fresh(ListValue, ())),)),
        )
    )


def test_a_name_unpacked_from_a_display_of_objects_is_that_object(tmp_path):
    # ``pair`` holds ``x``'s list (no ground display: ``x`` is a split's
    # value).  ``a`` is that list: ``c``, ``a``'s alias, and ``x`` read the
    # append; ``pair``, which holds it, is unknown, never the pre-call value.
    source = (
        "def f():\n"
        "    x = 'a b'.split()\n"
        "    pair = (x, [9])\n"
        "    a, b = pair\n"
        "    c = a\n"
        "    a.append('c')\n"
        "    return (c, x, pair)\n"
    )
    first, second, third = _only_return(tmp_path, source).elements
    after = fresh(ListValue, _strings("a", "b", "c"))
    assert first == after
    assert second == after
    assert _unknown_after_call(third)


def test_names_unpacked_from_a_call_are_its_members_for_the_door():
    # ``a`` and its alias ``c`` denote one object, the call's first member:
    # both read the object after the append.  Before, ``c`` kept the pre-call
    # reference (each read of ``a`` was its own object).
    source = (
        "def f(g):\n"
        "    a, b = g()\n"
        "    c = a\n"
        "    a.append(1)\n"
        "    return (c, a)\n"
    )
    reads = _substituted_return_reads(source)
    assert [read.kind for read in reads] == ["PathAfterCall"] * 2


def test_the_value_an_unpacked_member_came_from_holds_it():
    # ``pair`` holds ``a``'s object: after the append through ``a`` it reads
    # its value after the call, never the pre-call value.
    source = (
        "def f(g):\n"
        "    pair = g()\n"
        "    a, b = pair\n"
        "    alias = a\n"
        "    a.append(1)\n"
        "    return (pair, alias)\n"
    )
    reads = _substituted_return_reads(source)
    assert [read.kind for read in reads] == ["ReceiverAfterCall", "PathAfterCall"]


# -- The tree picks targets by reach; the door decides by value (#7757) -----
#
# ``_call_targets`` and the door's routing chose which receivers a call may
# change by matching the method's spelling against the container law's
# mutator names: ``c.append(1)`` on a source object took the door while
# ``c.reset()`` did not.  Every method call on a name a call can reach now
# takes the one door, whatever the method is spelled, and the receiver's
# value at reduce decides what it did.


_SOURCE_APPEND = (
    "class C:\n"
    "    tag = 'c'\n"
    "    def __init__(self):\n"
    "        self.items = [5]\n"
    "    def append(self, x):\n"
    "        self.items = [x]\n"
    "    def reset(self):\n"
    "        self.items = []\n"
)


def test_a_source_method_named_append_leaves_aliases_at_the_door_post_state():
    source = _SOURCE_APPEND + (
        "def f():\n"
        "    c = C()\n"
        "    alias = c\n"
        "    c.append(1)\n"
        "    return (alias, c)\n"
    )
    reads = _substituted_return_reads(source)
    assert [read.kind for read in reads] == ["PathAfterCall"] * 2


def test_a_source_method_named_append_is_not_the_list_rule(tmp_path):
    # ``C.append`` is the source's method: the value (an ``ObjectValue``)
    # takes the ordinary call, and the alias is the object after it, which
    # the call may have changed -- never a list's cited append.
    source = _SOURCE_APPEND + (
        "def f():\n"
        "    c = C()\n"
        "    alias = c\n"
        "    c.append(1)\n"
        "    return alias\n"
    )
    assert _unknown_after_call(_only_return(tmp_path, source))


def test_any_method_spelling_takes_the_same_door():
    source = _SOURCE_APPEND + (
        "def f():\n"
        "    c = C()\n"
        "    alias = c\n"
        "    c.reset()\n"
        "    return (alias, c)\n"
    )
    reads = _substituted_return_reads(source)
    assert [read.kind for read in reads] == ["PathAfterCall"] * 2


def test_a_list_method_that_does_not_mutate_keeps_the_list(tmp_path):
    # The door's value decides: ``count`` is no mutation the list law cites,
    # so the list and its alias are as they were.
    source = (
        "def f():\n"
        "    r = [1, 2]\n"
        "    a = r\n"
        "    n = r.count(1)\n"
        "    return (a, r, n)\n"
    )
    value = _only_return(tmp_path, source)
    kept = fresh(ListValue, _ints(1, 2))
    assert value.elements[:2] == (kept, kept)


def _traced_substitution(source, name):
    """``name``'s body substituted with the substitution trace (the
    threading an object place rides), and the tree's ``ClassDef``s."""
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.binding_state import SubstitutionTraceBuilderV1
    from sugar_source_tree.nodes import _SUBSTITUTION_TRACE_BUILDER, FunctionDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "one_rule_fixture.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )
    return function.substitute(
        {
            _SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(
                function.fragment.seal().cid
            )
        }
    )


def test_an_object_place_handed_to_an_opaque_call_is_rebound_by_the_one_rule():
    # No class attribute: ``C()`` is an object place.  ``g(c)`` used to mark
    # the place invalidated by its own rule; the one exposure rule now
    # rebinds ``c`` and its alias to their value after the call.
    from sugar_source_tree.container_mutation import _identity
    from sugar_source_tree.nodes import Return

    source = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self.items = [5]\n"
        "def f(g):\n"
        "    c = C()\n"
        "    alias = c\n"
        "    g(c)\n"
        "    return (alias, c)\n"
    )
    substituted = _traced_substitution(source, "f")
    places = [
        node for node in substituted.walk() if node.kind == "ObjectPlaceStateV1"
    ]
    assert places, "C() is an object place"
    assert not any(place.invalidated_by_opaque_call for place in places)
    returned = next(
        statement
        for statement in reversed(substituted.body)
        if isinstance(statement, Return)
    )
    reads = [_identity(read) for read in returned.value.elts]
    assert [read.kind for read in reads] == ["ReceiverAfterCall"] * 2


def test_self_handed_to_an_opaque_call_in_init_is_rebound_by_the_one_rule():
    # In an active ``__init__`` ``self`` is the receiver the class call
    # constructs (``ConstructedReceiverRef``), after ``self.x = ...`` its
    # field-store state: ``g(self)`` may change it, so ``self`` is its value
    # after the call, never the stored fields read as they were.
    from sugar_source_tree.binding_provenance import BindingCoordinateV1
    from sugar_source_tree.binding_state import BindingEntryV1
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.container_mutation import _identity, _state
    from sugar_source_tree.nodes import ClassDef
    from sugar_source_tree.tree import SourceFile

    source = (
        "class C:\n"
        "    def __init__(self, g):\n"
        "        self.x = [1]\n"
        "        g(self)\n"
    )
    tree = SourceFile(
        (source, "init_exposure_fixture.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    cls = next(
        node
        for node in tree.nodes()
        if isinstance(node, ClassDef) and node.name == "C"
    )
    initializer = cls._source_initializer()
    receiver_param = initializer.params[0]
    # The class call's frame, as ``ClassDef`` seats it for the initializer.
    coordinate = BindingCoordinateV1.mint(
        cls.fragment.seal().cid, receiver_param.fragment, ("receiver", 0)
    )
    receiver = cls._make_constructed_receiver_ref(coordinate.cid)
    scope = {receiver_param.name: BindingEntryV1(coordinate, receiver, None)}
    _body, _changed, net = initializer._substitute_body_tracked(
        initializer.body, scope
    )
    after = _identity(_state(net["self"]))
    assert after.kind == "ReceiverAfterCall"
    # Its value before the call is the receiver with ``x`` stored.
    assert after.prior.kind == "ReceiverFieldStoreState"


# The object a class call returns is ``self`` as ``__init__`` left it: the
# value a read of ``self`` after the initializer's last statement gives, in
# the context its end record left.  It was rebuilt from the initializer's
# field stores, so after ``g(self)`` the call returned the fields stored
# before the call -- a wrong answer.


_RESET_IN_INIT = (
    "class C:\n"
    "    def __init__(self, reset):\n"
    "        self.x = 1\n"
    "        reset(self)\n"
)


def test_the_class_call_reads_self_where_its_initializer_ends():
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
        ReceiverAfterCallSugar,
    )
    from sugar_source_tree.nodes import ClassDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (
            _RESET_IN_INIT,
            "init_end_fixture.py",
            blake3_512_of(_RESET_IN_INIT.encode()),
        ),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    cls = next(
        node
        for node in tree.nodes()
        if isinstance(node, ClassDef) and node.name == "C"
    )
    body = cls.source_visible_constructor_frame().body
    # ``self`` after ``reset(self)``: its value after the call the one
    # exposure rule rebinds it to, never the stored fields.
    assert type(body.receiver_at_end) is ReceiverAfterCallSugar
    assert not body.returns_early


def test_self_exposed_in_init_is_the_object_the_class_call_returns(tmp_path):
    source = _RESET_IN_INIT + "def f(g):\n    return C(g)\n"
    returns, _halts = _returns(tmp_path, source)
    assert returns
    assert all(_unknown_after_call(value) for value in returns)


def test_a_field_of_self_exposed_in_init_is_undecided_not_the_stored_one(tmp_path):
    source = _RESET_IN_INIT + "def f(g):\n    return C(g).x\n"
    returns, _halts = _returns(tmp_path, source)
    assert returns
    assert TermValue(1) not in returns


def test_the_class_call_returns_every_store_of_its_initializer(tmp_path):
    source = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "        self.y = 2\n"
        "def f():\n"
        "    c = C()\n"
        "    return (c.x, c.y)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue(_ints(1, 2))


def test_the_class_call_returns_self_after_a_method_call_on_it(tmp_path):
    # ``self.helper()`` takes the one door: the receiver is the door's value
    # after the call (a source object a method of its own reaches may have
    # changed), so the instance is that value -- what a read of ``self``
    # after the call gives -- never ``x`` alone as stored before it.
    source = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "        self.helper()\n"
        "    def helper(self):\n"
        "        self.z = 3\n"
        "def f():\n"
        "    return C()\n"
    )
    returns, _halts = _returns(tmp_path, source)
    assert returns
    assert all(_unknown_after_call(value) for value in returns)


# -- The leftovers of #8130 (#7757) -----------------------------------------
#
# Two members of one opaque value were taken to be two objects: after ``a, b
# = g()`` a mutation through ``a`` left ``b`` (and anything holding it) its
# old value, though ``g`` may return one list twice.  ``f()[0] += 1`` kept the
# ordinary augmented store beside the door.  A setdefault on a path
# (``self.d.setdefault(k, []).append(x)``) was an ordinary call.  A starred
# member (``*m``) was no path root: ``m[0].append(1)`` left ``m`` unknown.


def _held_by_the_mutation(read):
    """``read`` is its value after the call, held (no ``sharer`` rule, which
    kept a value a builtin container's cited mutation changed)."""
    return (
        read.kind == "ReceiverAfterCall"
        and bool(read.rules)
        and not any(rule[2] for rule in read.rules)
    )


def test_two_members_of_one_opaque_value_may_be_one_object(tmp_path):
    # ``pair`` holds ``x`` twice: ``b`` (and its alias ``c``) is ``a``, and
    # so is ``x``.  The lift kept ``b``, ``c`` and ``x`` at the pre-call
    # ``['a', 'b']``.  Which object each is, is undecided: the append's
    # opaque post-state, never the old value.
    source = (
        "def f():\n"
        "    x = 'a b'.split()\n"
        "    pair = [x] * 2\n"
        "    a, b = pair\n"
        "    c = b\n"
        "    a.append('c')\n"
        "    return (b, c, x)\n"
    )
    stale = fresh(ListValue, _strings("a", "b"))
    for value in _only_return(tmp_path, source).elements:
        assert value != stale
        assert _unknown_after_call(value)


def test_a_mutation_through_one_member_holds_every_other_member():
    # Discriminating: ``b`` and ``outer`` (which holds ``b``) only shared
    # with ``a`` before (``sharer``: a list's cited append kept them).
    source = (
        "def f(g):\n"
        "    a, b = g()\n"
        "    outer = [b]\n"
        "    a.append(1)\n"
        "    return (b, outer)\n"
    )
    reads = _substituted_return_reads(source)
    assert [read.kind for read in reads] == ["ReceiverAfterCall"] * 2
    assert all(_held_by_the_mutation(read) for read in reads)


def test_a_starred_member_holds_the_other_members():
    # ``m`` is a new list of ``g()``'s later members, any of which may be
    # ``a``: it and its alias are the append's post-state.  Before, ``m``
    # denoted an object nothing related to ``a`` and kept its value.
    source = (
        "def f(g):\n"
        "    a, *m = g()\n"
        "    alias = m\n"
        "    a.append(1)\n"
        "    return (m, alias)\n"
    )
    reads = _substituted_return_reads(source)
    assert [read.kind for read in reads] == ["ReceiverAfterCall"] * 2
    assert all(_held_by_the_mutation(read) for read in reads)


def test_a_starred_member_is_its_own_path_root(tmp_path):
    # ``m`` is the new list ``[x, 5]``; ``m[0].append`` takes the path door
    # from it, and ``c``, its alias, reads the root after the call.  Before,
    # ``m`` was no path root and the call left both unknown.
    source = (
        "def f():\n"
        "    x = 'a b'.split()\n"
        "    pair = (0, x, 5)\n"
        "    a, *m = pair\n"
        "    c = m\n"
        "    m[0].append('c')\n"
        "    return (c, m)\n"
    )
    after = fresh(ListValue, (fresh(ListValue, _strings("a", "b", "c")), TermValue(5)))
    assert _only_return(tmp_path, source) == TupleValue((after, after))


def _substituted_body(source):
    """``f``'s body statements after substitution."""
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "temporary_fixture.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "f"
    )
    return function.substitute({}).body


def test_an_augmented_item_store_on_a_temporary_takes_the_door():
    from sugar_source_tree.nodes import AugAssign, ContainerMutationStatement

    source = "def f(g):\n    g()[0] += 1\n    return 0\n"
    body = _substituted_body(source)
    assert not any(isinstance(statement, AugAssign) for statement in body)
    (statement,) = [
        statement
        for statement in body
        if isinstance(statement, ContainerMutationStatement)
    ]
    assert tuple(statement.names) == ()
    (call,) = statement.evaluated
    assert call.method == "__setitem__"
    assert getattr(call, "operator_kind", None) is not None


def test_an_augmented_item_store_on_a_temporary_halts_before_the_store(tmp_path):
    source = (
        "def f():\n"
        "    try:\n"
        "        [1][3] += 1\n"
        "    except IndexError:\n"
        "        return 'caught'\n"
        "    return 'no'\n"
    )
    assert _only_return(tmp_path, source) == StringValue("caught")


def test_an_augmented_store_through_an_expression_never_leaves_a_stale_name(
    tmp_path,
):
    # ``(a or b)[0] += 10`` stores on ``a``'s list.  The ordinary augmented
    # store rebound nothing: ``a`` and its alias read the pre-store ``[1]``.
    # The store may change every object its receiver reaches; each is its
    # value after the store, which a list's is unknown.
    source = (
        "def f():\n"
        "    a = [1]\n"
        "    b = [2]\n"
        "    alias = a\n"
        "    (a or b)[0] += 10\n"
        "    return (a, alias)\n"
    )
    for value in _only_return(tmp_path, source).elements:
        assert value != fresh(ListValue, _ints(1))
        assert _unknown_after_call(value)


def test_a_setdefault_through_a_subscript_path_is_seen_by_every_alias(tmp_path):
    # Discriminating: the ordinary call left ``e`` reading the pre-call
    # ``[{}]``.
    source = (
        "def f():\n"
        "    d = [{}]\n"
        "    e = d\n"
        "    d[0].setdefault('k', []).append('x')\n"
        "    return e\n"
    )
    assert _only_return(tmp_path, source) == fresh(
        ListValue,
        (
            fresh(
                DictValue,
                ((StringValue("k"), fresh(ListValue, _strings("x"))),),
            ),
        ),
    )


def test_a_setdefault_through_an_attribute_path_changes_the_held_list(tmp_path):
    # ``L`` is the object at ``c.d['k']``; the ordinary call left it ``[1]``.
    source = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self.d = {'k': [1]}\n"
        "def f():\n"
        "    c = C()\n"
        "    L = c.d['k']\n"
        "    c.d.setdefault('k', []).append(2)\n"
        "    return (L, c.d['k'])\n"
    )
    after = fresh(ListValue, _ints(1, 2))
    assert _only_return(tmp_path, source) == TupleValue((after, after))


def test_a_bound_setdefault_pop_through_a_path_changes_every_alias(tmp_path):
    source = (
        "def f():\n"
        "    L = [1, 2]\n"
        "    d = [{'x': L}]\n"
        "    e = d\n"
        "    x = d[0].setdefault('x', []).pop()\n"
        "    return (x, L, e)\n"
    )
    after = fresh(ListValue, _ints(1))
    assert _only_return(tmp_path, source) == TupleValue(
        (
            TermValue(2),
            after,
            fresh(ListValue, (fresh(DictValue, ((StringValue("x"), after),)),)),
        )
    )
