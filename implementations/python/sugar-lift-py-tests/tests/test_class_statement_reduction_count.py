"""A class statement is reduced once; every class call reads that one result.

``a = Box(1); b = Box(2)`` used to reduce ``Box``'s class statement at every
class call: ``ClassConstructorBodySugar.desugar`` reduced its ``definition``
each time (#7794), and before #7804 a second time per call only to read
``class_definition_cid``.  Python runs a class statement once and every call
reads the class it bound, so a module-level statement's outcome is now reduced
once and kept with its sugar (``ClassDefinitionSugar.desugar``); every call
answers with it.  The count below is reductions of the statement, not reads.

The solver twin differs in one literal: the field read off the constructed
receiver, truthful ``sat``, lying ``unsat``.  Since #7757 step 6 (#8738) a
class call is its coordinate and edge and the reduction never runs
``__init__``: the field is read through the class's contract
(``python:after(<call result>, "out")``), joined at prove (step 7, #8746).
``__init__``'s own row stores on a formal with no actual and may owe it, so
the truthful half is read on the test function's claims.

At the reduction each class call is the edge's two faces, so the test
function completes on one face and halts on the others (the edge's
undetermined raises, and the undecided field read and comparison over its
result); the class statement is still reduced once, by the module's run.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

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
    test_line = _TWIN.splitlines().index("def test_box():") + 1
    assert truthful.verdict != "unsat"
    assert claim_verdict(truthful.prove_doc, claims_from_line=test_line) == "sat"
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
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    reductions = _counting_reductions(monkeypatch)
    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    from sugar_lift_py_tests.outcome import Completed

    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name.startswith("test_")
    )
    # Each class call is the edge's two faces (#7757 step 6): the function
    # completes on one face, never as one completion alone.
    outcome = function_universe_outcome(function)
    assert any(isinstance(face, Completed) for face in outcome.exits), outcome
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
# built for it (``Assign._object_place_state`` returned ``None`` through the
# deleted ``_constructed_floor_value`` before the address was read), and the statement
# is still reduced once however often the class is called: by the module's
# one run, which is where Python runs it.
#
# The class body raises at the class statement, never at a call (#7757 item
# 21).  A function called after import reads ``Box`` as the class the
# module's run bound under the statement's key, on the run's completed arms
# (``DecoratorApplicationSugar._bound_by_statement``, ``ModuleFinalValue``):
#
# - ``int(os.environ["LIMIT"])`` may raise.  The run completes on one arm,
#   which bound the class; its halts are the run's, so no class call carries
#   them.  (Before, #7794 put the statement's three halts on every class
#   call.)  The function completed alone until #7757 step 6; each class call
#   is now the edge's two faces.
# - ``int("x")`` is a builtin over a ground operand, decided by the
#   builtin's own semantics (``cpython_cited_fold``): Python raises
#   ``ValueError``, always.  The run completes on no arm and binds no class,
#   so no import completes and the read of ``Box`` is the run's halt
#   (``tree_enumerate.module_run_halts``): the first class call is that
#   ``ValueError`` and nothing after it runs, read off the module's one run,
#   never off a second reduction of the statement.
# ---------------------------------------------------------------------------

_NOT_ONE_COMPLETION = {
    "field-may-raise": '    limit = int(os.environ["LIMIT"])\n',
    "field-int-of-text": '    limit = int("x")\n',
}
_USES = {
    "one-call": ("    a = Box(1)\n    assert a.n == 1\n", 1),
    "two-calls": ("    a = Box(1)\n    b = Box(2)\n    assert a.n == 1\n", 2),
}
# Class bodies that never complete: the module run binds no class, and the
# exception its one halt raises.
_BODY_ALWAYS_RAISES = {"field-int-of-text": "ValueError"}


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
    if body in _BODY_ALWAYS_RAISES:
        assert not any(isinstance(face, Completed) for face in outcome.exits)
        names = [
            getattr(face.effect, "exception_name", None)
            for face in outcome.exits
            if isinstance(face, Halted)
        ]
        assert names.count(_BODY_ALWAYS_RAISES[body]) == 1, names
        return
    # The run's halts are the run's: no class call carries the field's
    # ``KeyError``/``ValueError``.  Each class call is the edge's two faces
    # (#7757 step 6), so the function completes on one face and halts on the
    # edges' undetermined raises (and the undecided read and comparison over
    # the call's result), never on a halt of the class statement.
    assert any(isinstance(face, Completed) for face in outcome.exits), outcome
    carried = [
        getattr(face.effect, "exception_name", None)
        for face in outcome.exits
        if isinstance(face, Halted)
    ]
    assert not {"KeyError", "ValueError"} & set(carried), carried
