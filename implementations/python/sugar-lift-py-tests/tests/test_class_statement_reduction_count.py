"""Plan row 1 (step 6): reading a class's content address reduces nothing.

``a = Box(1)`` builds an object place state during the temporal rewrite. That
used to reduce ``Box``'s class statement twice per class call: once inside the
call (``ClassConstructorBodySugar.desugar`` reduces its ``definition``), and a
second time only to read ``class_definition_cid``, which the statement's sugar
already holds as a property. The second one is deleted.

The first one is still a reduction of the statement at every call, where the
standard is one reduction of one statement ("reduce once"). It is carried by
how the temporal rewrite substitutes a module-level definition into each
function, so it is #7794 (plan row 7, the temporal row) and is not fixed here.
The count below is today's measured number, one per class call, not a target:
when #7794 lands this test goes red because the count dropped, and the number
is then lowered to one per statement.

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


def _class_statement_reductions(source: str, monkeypatch) -> int:
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.class_definition_sugar import ClassDefinitionSugar
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    reductions: Counter[str] = Counter()
    reduce_statement = ClassDefinitionSugar.desugar

    def counted(self, ctx=None):
        reductions[self.class_name] += 1
        return reduce_statement(self, ctx)

    monkeypatch.setattr(ClassDefinitionSugar, "desugar", counted)
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
    ("source", "class_calls"),
    [(_ONE_CALL, 1), (_TWO_CALLS, 2)],
    ids=["one-call", "two-calls"],
)
def test_reading_the_class_address_does_not_reduce_the_statement(
    source: str, class_calls: int, monkeypatch
) -> None:
    """The probe: reductions of ``Box``'s class statement in one function.

    Two per class call before this deletion (2 and 4 for these sources), one
    per class call after it (1 and 2). The one left is #7794.
    """

    assert _class_statement_reductions(source, monkeypatch) == class_calls


# ---------------------------------------------------------------------------
# The deleted exit. The lines this change removed also returned ``None`` when
# their own reduction of the class statement was not a single completion. That
# case never reaches them: a class statement that is not one completion makes
# the class call on the same line not one completion either, and
# ``Assign._object_place_state`` already returned ``None`` for that
# (``_constructed_floor_value``), before the address is read. So no place state
# is built, the statement is reduced once per class call (inside the call), and
# the statement's halts are faces of the function that calls the class.
#
# That last fact is #7794 and is wrong by Python (the class body raises at the
# class statement, never at the call); it is pinned here as what happens, the
# same before and after this change.
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
    from sugar_lift_py_tests.sugar.class_definition_sugar import ClassDefinitionSugar
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

    reductions: Counter[str] = Counter()
    reduce_statement = ClassDefinitionSugar.desugar

    def counted(self, ctx=None):
        reductions[self.class_name] += 1
        return reduce_statement(self, ctx)

    monkeypatch.setattr(nodes.Assign, "_object_place_state", recorded)
    monkeypatch.setattr(ClassDefinitionSugar, "desugar", counted)
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
    assert reductions["Box"] == class_calls
    assert isinstance(outcome, ExitSet), outcome
    assert [type(face) for face in outcome.exits] == [Completed] + [Halted] * (
        _BODY_HALTS[body] * class_calls
    )
