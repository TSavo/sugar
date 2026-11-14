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
    assert _only_return(tmp_path, source) == ListValue(_ints(1))


def test_a_subscript_receiver_append_is_seen_through_the_dict(tmp_path):
    source = "def f():\n    d = {'k': []}\n    d['k'].append(1)\n    return d\n"
    assert _only_return(tmp_path, source) == DictValue(
        ((StringValue("k"), ListValue(_ints(1))),)
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
            ListValue(_ints(1)),
            DictValue(
                (
                    (StringValue("k"), ListValue(_ints(1))),
                    (StringValue("j"), TermValue(1)),
                )
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
    assert first == ListValue(_ints(1))
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
        (ListValue(_ints(1)), ListValue(_ints(1)), TermValue(2), TermValue(0))
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
        (ListValue(_ints(1)), ListValue((ListValue(_ints(1)),)))
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
    assert _only_return(tmp_path, source) == DictValue(
        ((StringValue("k"), ListValue(_ints(0, 1))),)
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
    assert _only_return(tmp_path, source) == ListValue(_strings("a", "b", "c"))


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
        (ListValue(_strings("a", "b", "c")), ListValue(_strings("a", "b", "c")))
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
        (StringValue("b"), ListValue(_strings("a")))
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
    assert value != ListValue((ListValue(_strings("a", "b")),))
    assert _unknown_after_call(value)
