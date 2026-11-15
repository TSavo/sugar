"""A function's contract states what it leaves in the closure cells it
rebinds (#7757 step 7, the owner's ruling "Edge, join at prove").

A caller reads its cell after a same-file call as ``python:after(<call
result>, "cell:<name>")``, keyed on the call
(``container_mutation._havoc``'s ``after``).  The callee's own contract
states that term over ``out`` on each completed arm
(``UniverseValue.after_facts``), so the join decides the caller's read.  The
contract states only a value its own inputs determine
(``universe_value.stated_by_its_inputs``): what it does not determine (an
append on a cell whose type nothing here decides) is not stated, and the
caller's read stays undecided by name.  These are unit checks of the
contract; the twins are ``test_function_value_application_twins``.
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
    # result over the cell's input, the one undecided binary form.
    for post in posts:
        assert "python:after" in post, post
        assert "cell:n" in post, post
        assert "+=" in post, post


_APPENDED = """\
def test_append():
    xs = []

    def add():
        xs.append(1)

    add()
    assert len(xs) == 1
"""


def test_an_append_on_an_undecided_cell_is_not_stated() -> None:
    # ``xs`` is not rebound, and what the append leaves in an object of a
    # type nothing here decides is not determined by the contract's inputs.
    for post in _posts(_APPENDED, "add"):
        assert "python:after" not in post, post


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


def test_an_early_return_states_on_the_arm_that_ran_on() -> None:
    # The arm the ``return`` ended left the frame before ``n += 1``: it
    # states nothing.  The arm that ran to the end states the in-place
    # result over the cell's input (#7757 step 7).
    posts = _posts(_EARLY_RETURN, "bump")
    stated = [post for post in posts if "python:after" in post]
    assert stated, posts
    assert len(stated) < len(posts), posts
    for post in stated:
        assert "cell:n" in post, post
        assert "+=" in post, post


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


def test_a_rebinding_in_a_live_loop_is_not_stated() -> None:
    # A live loop's result is its own publication, keyed on the loop
    # (``python:loop.*``): no input determines it, so nothing is stated.
    for post in _posts(_LIVE_LOOP, "bump"):
        assert "python:after" not in post, post


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
    # cell is stated as each item's in-place result left it.
    posts = _posts(_UNROLLED_LOOP, "bump")
    assert posts, posts
    for post in posts:
        assert "python:after" in post, post
        assert "cell:n" in post, post
        assert "+=" in post, post
