"""A class statement is reduced once; every class call reads that one result.

``a = Box(1); b = Box(2)`` used to reduce ``Box``'s class statement at every
class call: ``ClassConstructorBodySugar.desugar`` reduced its ``definition``
each time (#7794), and before #7804 a second time per call only to read
``class_definition_cid``.  Python runs a class statement once and every call
reads the class it bound, so a module-level statement's outcome is now reduced
once and kept with its sugar (``ClassDefinitionSugar.desugar``); every call
answers with it.  The count below is reductions of the statement, not reads.

The solver twin differs in one literal: the field read off the constructed
receiver is decided by the floor, truthful ``sat``, lying ``unsat``.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_TWIN = (
    "class Box:\n"
    "    def __init__(self, n):\n"
    "        self.n = n\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    a = Box(1)\n"
    "    assert a.n == {claim}\n"
)


def test_a_field_of_a_constructed_receiver_reaches_the_solver(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(tmp_path / "t", _TWIN.format(claim=1))
    lying = run_source_through_real_solver(tmp_path / "l", _TWIN.format(claim=2))
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"


_ONE_CALL = _TWIN.format(claim=1)
_TWO_CALLS = (
    "class Box:\n"
    "    def __init__(self, n):\n"
    "        self.n = n\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    a = Box(1)\n"
    "    b = Box(2)\n"
    "    assert a.n == 1\n"
)
_THREE_CALLS = (
    "class Box:\n"
    "    def __init__(self, n):\n"
    "        self.n = n\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    a = Box(1)\n"
    "    b = Box(2)\n"
    "    c = Box(3)\n"
    "    assert a.n == 1\n"
)


def _counting_reductions(monkeypatch) -> Counter[str]:
    """Count reductions of a class statement (not reads of its outcome)."""
    from sugar_lift_py_tests.sugar.class_definition_sugar import ClassDefinitionSugar

    reductions: Counter[str] = Counter()
    reduce_statement = ClassDefinitionSugar._reduce_statement

    def counted(self, ctx):
        reductions[self.class_name] += 1
        return reduce_statement(self, ctx)

    monkeypatch.setattr(ClassDefinitionSugar, "_reduce_statement", counted)
    return reductions


def _class_statement_reductions(source: str, monkeypatch) -> int:
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    reductions = _counting_reductions(monkeypatch)
    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name.startswith("test_")
    )
    assert isinstance(function_universe_outcome(function), Complete)
    return reductions["Box"]


@pytest.mark.parametrize(
    "source",
    [_ONE_CALL, _TWO_CALLS, _THREE_CALLS],
    ids=["one-call", "two-calls", "three-calls"],
)
def test_a_class_statement_is_reduced_once_however_often_it_is_called(
    source: str, monkeypatch
) -> None:
    """Reductions of ``Box``'s class statement per function: one.

    Two per class call before #7804 (2, 4, 6), one per class call before
    #7794 (1, 2, 3), one per statement now (1, 1, 1).
    """

    assert _class_statement_reductions(source, monkeypatch) == 1


# ---------------------------------------------------------------------------
# A class statement that is not one completion.  No object place state is
# built for it (``Assign._object_place_state`` returns ``None`` through
# ``_constructed_floor_value`` before the address is read), and the statement
# is still reduced once however often the class is called.
#
# Each class call still carries the statement's halts as faces of the function
# that calls the class.  That is wrong by Python (the class body raises at the
# class statement, never at the call) and is plan row 7, the temporal row; it
# is pinned here as what happens.
# ---------------------------------------------------------------------------

_NOT_ONE_COMPLETION = {
    "field-may-raise": '    limit = int(os.environ["LIMIT"])\n',
    "field-int-of-text": '    limit = int("x")\n',
}
_USES = {
    "one-call": ("    a = Box(1)\n    assert a.n == 1\n", 1),
    "two-calls": ("    a = Box(1)\n    b = Box(2)\n    assert a.n == 1\n", 2),
}
# Halted faces one class call carries from the class body.
_BODY_HALTS = {"field-may-raise": 2, "field-int-of-text": 1}


@pytest.mark.parametrize("body", sorted(_NOT_ONE_COMPLETION))
@pytest.mark.parametrize("use", sorted(_USES))
def test_a_class_statement_that_is_not_one_completion_builds_no_place_state(
    body: str, use: str, monkeypatch
) -> None:
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree import nodes
    from sugar_source_tree.tree import SourceFile

    statements, class_calls = _USES[use]
    source = (
        "import os\n\n\nclass Box:\n"
        + _NOT_ONE_COMPLETION[body]
        + "\n    def __init__(self, n):\n        self.n = n\n\n\n"
        + "def test_box():\n"
        + statements
    )

    place_states: list[object] = []
    build_place_state = nodes.Assign._object_place_state

    def recorded(self, entry):
        state = build_place_state(self, entry)
        place_states.append(state)
        return state

    monkeypatch.setattr(nodes.Assign, "_object_place_state", recorded)
    reductions = _counting_reductions(monkeypatch)
    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.FunctionDef) and node.name.startswith("test_")
    )
    outcome = function_universe_outcome(function)

    assert place_states == [None] * class_calls
    assert reductions["Box"] == 1
    assert isinstance(outcome, ExitSet), outcome
    assert [type(face) for face in outcome.exits] == [Completed] + [Halted] * (
        _BODY_HALTS[body] * class_calls
    )
