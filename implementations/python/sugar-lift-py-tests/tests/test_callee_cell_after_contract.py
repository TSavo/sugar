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


def test_a_rebinding_under_a_branch_is_not_stated() -> None:
    # The read where the body ends is stated only where every binding of
    # the cell is a simple top-level statement of the body.
    for post in _posts(_BRANCH, "bump"):
        assert "python:after" not in post, post
