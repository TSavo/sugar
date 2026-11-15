"""An early ``return``'s arms are the two faces of the ``if`` test that
returns (#7757, step 6).

``def f(c): if c: return 1; return 2`` has two completed arms: the one the
``return 1`` ends, and the one that goes on to ``return 2``.  Each was guarded
by the ``if``'s branch slot, ``py.truthy(python:branch_result(<slot>))``,
and the slot's authentication (slot iff test) is an entry that mints no
row: the function's contract stated ``slot -> out == 1`` and ``not slot ->
out == 2`` over a flag no input decides, so for one input both arms stood
satisfiable and a lie (``f(True) == 2``) could read ``sat``.  Each arm is now
guarded by the test's own condition (``IfSugar._select_suites``), so the
arms are exactly the two faces of the test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _outcome(source: str, name: str):
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )
    return function_universe_outcome(function)


_IDENTITY = """\
def f(x):
    if x is None:
        return 1
    return 2
"""


def test_no_early_return_arm_is_guarded_by_the_branch_slot() -> None:
    from sugar_lift_py_tests.floor.universe_value import UniverseValue
    from sugar_lift_py_tests.outcome import Completed

    outcome = _outcome(_IDENTITY, "f")
    completed = [
        exit_
        for exit_ in outcome.exits
        if isinstance(exit_, Completed) and isinstance(exit_.value, UniverseValue)
    ]
    assert completed, outcome
    for exit_ in completed:
        assert "python:branch_result" not in repr(exit_.guard), exit_.guard
        post = str(exit_.value.post())
        assert "python:branch_result" not in post, post


_TWINS = {
    # ``if c:`` over a formal: the test's truth is the formal's.
    "truth-of-a-formal": (
        "def f(c):\n"
        "    if c:\n"
        "        return 1\n"
        "    return 2\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert f(True) == {x}\n"
    ),
    # ``if x is None:``: the test's condition is an identity no read owes.
    "identity-test": (
        _IDENTITY + "\n\ndef test_f():\n    assert f(None) == {x}\n"
    ),
}


@pytest.mark.parametrize("shape", sorted(_TWINS))
def test_the_truthful_half_is_sat(shape: str, tmp_path: Path) -> None:
    result = run_source_through_real_solver(
        tmp_path / "t", _TWINS[shape].format(x="1")
    )
    assert result.verdict == "sat"


@pytest.mark.parametrize("shape", sorted(_TWINS))
def test_the_lying_half_is_never_sat(shape: str, tmp_path: Path) -> None:
    # The arm that went on past the ``return`` is under the test's
    # complement: for the input that takes the ``return``, it is not
    # satisfiable, so ``f(...) == 2`` never reads ``sat``.
    result = run_source_through_real_solver(
        tmp_path / "l", _TWINS[shape].format(x="2")
    )
    assert result.verdict != "sat"
