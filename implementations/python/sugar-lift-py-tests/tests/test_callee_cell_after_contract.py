"""A function's contract states what it leaves in the closure cells it
rebinds (#7757 step 7, the owner's ruling "Edge, join at prove").

A caller reads its cell after a same-file call as ``python:after(<call
result>, "cell:<name>")``, keyed on the call
(``container_mutation._havoc``'s ``after``).  The callee's own contract
states that term over ``out`` on each completed arm
(``UniverseValue.after_facts``), so the join decides the caller's read.  The
contract states only a value its own inputs determine
(``universe_value.stated_by_its_inputs``): what it does not determine is
not stated, and the caller's read stays undecided by name.  An append on a
cell or a parameter is the dispatched edge over its class input
(``class:cell:<name>``, ``class:<param>``), and the object is stated as that
call leaves its receiver, ``python:after(<call result>, "0")``, which prove
decides where the caller binds the class to a builtin whose law answers the
call (#7757 step 7).  These are unit checks of the contract; the twins are
``test_function_value_application_twins``.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _posts(source: str, name: str) -> list:
    """The post of every completed arm of ``name``'s own contract, spelled."""
    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )
    outcome = function_universe_outcome(function)
    return [
        str(exit_.value.post())
        for exit_ in outcome.exits
        if isinstance(exit_, Completed) and isinstance(exit_.value, UniverseValue)
    ]


_REBOUND = """\
def test_count():
    n = 0

    def bump():
        nonlocal n
        n += 1

    bump()
    assert n == 1
"""


def test_a_nonlocal_rebinding_is_stated_over_the_cell_after_the_call() -> None:
    posts = _posts(_REBOUND, "bump")
    assert posts, posts
    # Every completed arm states what it left in the cell: the in-place
    # result over the cell's input, the one undecided binary form.  ``n += 1``
    # over an undecided ``n`` is the ``+`` form, keyed per evaluation
    # (``python:binary_result("+", cell:n, 1, <key>)``; #9017 decision 5:
    # no ``+=`` spelling is kept beside it).
    for post in posts:
        assert "python:after" in post, post
        assert "cell:n" in post, post
        assert "python:binary_result" in post, post
        assert "value='+'" in post, post
        assert "+=" not in post, post


_APPENDED = """\
def test_append():
    xs = []

    def add():
        xs.append(1)

    add()
    assert len(xs) == 1
"""


def test_an_append_on_a_cell_is_stated_over_the_dispatched_call() -> None:
    # ``xs.append(1)`` on the cell's input is the dispatched edge over its
    # class input ``class:cell:xs`` (#7757 step 7): the cell is stated as
    # that call leaves its receiver, ``python:after(<call result>, "0")``,
    # over the contract's own inputs; never the cell's input itself.
    posts = _posts(_APPENDED, "add")
    stated = [post for post in posts if "python:after" in post]
    assert stated, posts
    for post in stated:
        assert "cell:xs" in post, post
        assert "dispatch:append" in post, post
        assert "class:cell:xs" in post, post


_APPENDED_TO_A_PARAMETER = """\
def add(xs):
    xs.append(1)


def test_append():
    ys = []
    add(ys)
    assert len(ys) == 1
"""


def test_an_append_on_a_parameter_is_stated_over_the_dispatched_call() -> None:
    # The parameter's object after the call, under the parameter's own
    # name: as the dispatched ``append`` over ``class:xs`` left it.
    posts = _posts(_APPENDED_TO_A_PARAMETER, "add")
    stated = [post for post in posts if "python:after" in post]
    assert stated, posts
    for post in stated:
        assert "dispatch:append" in post, post
        assert "class:xs" in post, post


_GLOBAL_STORED_IN_PLACE = """\
G = [1]


def bump():
    G[0] = 2


def test_bump():
    bump()
    assert G[0] == 2
"""


def test_a_global_stored_in_place_is_stated_over_the_dispatched_call() -> None:
    # ``G[0] = 2`` on the global's input is the dispatched ``__setitem__``
    # over its class input ``class:global:G`` (#7757 step 7): the global is
    # stated as that call leaves its receiver, under ``global:G``, never the
    # global's input itself.
    posts = _posts(_GLOBAL_STORED_IN_PLACE, "bump")
    stated = [post for post in posts if "python:after" in post]
    assert stated, posts
    for post in stated:
        assert "global:G" in post, post
        assert "__setitem__" in post, post
        assert "class:global:G" in post, post


_BRANCH = """\
def test_count(c):
    n = 0

    def bump():
        nonlocal n
        if c:
            n += 1

    bump()
    assert n >= 0
"""


def test_a_rebinding_under_a_branch_states_no_branch_slot() -> None:
    # A rebinding under a branch is read where the body ends, each arm in
    # the context it left (``FunctionUniverseSugar._after``).  An arm whose
    # read the branch's join leaves two-faced states nothing; whatever an
    # arm states is its own value over the cell's input, never the
    # branch's slot (``python:branch_result``), which no input determines.
    posts = _posts(_BRANCH, "bump")
    assert posts, posts
    for post in posts:
        assert "python:branch_result" not in post, post
        if "python:after" in post:
            assert "cell:n" in post, post


_EARLY_RETURN = """\
def test_count():
    n = 0

    def bump():
        nonlocal n
        if n > 5:
            return
        n += 1

    bump()
    assert n == 1
"""


def test_a_cell_read_after_an_early_returns_test_is_not_stated() -> None:
    # The arm the ``return`` ended left the frame before ``n += 1``: it
    # states nothing.  The arm that ran on reads ``n`` after ``n > 5``,
    # which over the cell's free input may run code (``__gt__``) that
    # rebinds a ``nonlocal`` cell: the read is another evaluation, the
    # exposure rule's unknown (``container_mutation._ambient_targets``,
    # #8823/#8847), and ``n += 1`` over it names no input, so nothing is
    # stated (``stated_by_its_inputs``; scorecard 43752693483: the one post
    # is the ``return`` arm's).  Decided where the contract states the cell
    # after the test over its class input (step 7).
    posts = _posts(_EARLY_RETURN, "bump")
    assert posts, posts
    for post in posts:
        assert "python:after" not in post, post


_LIVE_LOOP = """\
def test_count(xs):
    n = 0

    def bump():
        nonlocal n
        for x in xs:
            n += x

    bump()
    assert n >= 0
"""


def test_a_rebinding_in_a_live_loop_reads_the_recurrences_value() -> None:
    # A live loop over the cell ``xs`` runs its one symbolic item, and the
    # recurrence carries the ``nonlocal`` cell ``n`` through its header
    # alone, published through its post-loop key.  The item begins with the
    # recurrence's value of that key (``LoopRecurrenceSugar._recurrence_starts``),
    # what earlier items handed on, never the value before the loop: the
    # read of ``n`` in ``n += x`` owes the undecided member, and the function
    # is no longer refused (before, the header was left unbound in the item
    # and the read was refused by name, scorecard 43752693483).  Whatever the
    # contract states of the cell is the recurrence's value, never a value
    # made up for it.
    posts = _posts(_LIVE_LOOP, "bump")
    assert posts, posts
    for post in posts:
        if "python:after" in post and "cell:n" in post:
            assert "python:loop.recurrence" in post, post


_UNROLLED_LOOP = """\
def test_count():
    n = 0

    def bump():
        nonlocal n
        for x in (1, 2):
            n += x

    bump()
    assert n == 3
"""


def test_a_rebinding_in_a_decided_loop_is_stated() -> None:
    # A loop over a display is unrolled: its result is decided, and the
    # cell is stated as each item's in-place result left it: one ``+`` form
    # per item, each keyed by its own item's evaluation (#9017 decision 5).
    posts = _posts(_UNROLLED_LOOP, "bump")
    assert posts, posts
    for post in posts:
        assert "python:after" in post, post
        assert "cell:n" in post, post
        assert post.count("python:binary_result") == 2, post
        assert "value='+'" in post, post
        assert "+=" not in post, post


_GLOBAL = """\
G = 0


def reset():
    global G
    G = 5


def test_reset():
    reset()
    assert G == 5
"""


def test_a_global_rebinding_is_stated_over_the_global_after_the_call() -> None:
    # A module global the ``def`` declares ``global`` is read where the body
    # ends, as a cell is, under its formal ``global:G``.
    posts = _posts(_GLOBAL, "reset")
    assert posts, posts
    for post in posts:
        assert "python:after" in post, post
        assert "global:G" in post, post
