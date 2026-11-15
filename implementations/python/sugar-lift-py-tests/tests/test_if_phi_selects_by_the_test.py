"""The assignment phi after a symbolic ``if`` selects by the ``if``'s own
test, never by its untied branch slot (#7757, step 6).

``def f(c): if c: x = 1 else: x = 2; return x`` reads ``x`` after the ``if``
through the phi ``1 if <slot> else 2`` (``If.substitute``).  The slot was
read as its coordinate, ``py.truthy(python:branch_result(<slot>))``, which no
contract row ties to the test (its authentication mints nothing), so the
contract stated ``out == ite(flag, 1, 2)`` over a free flag and the lie
``f(True) == 2`` was satisfiable with the flag false.  The path after a
symbolic ``if`` now reads its slot as the test's condition
(``GuardedFaces.readings``), the same condition its arms are guarded by
(#8894), and a phi, a guarded binding read and a ``del`` select by it
(``branch_result_reading``).  An ``if`` nested in a suite hands its reading
out of the enclosing ``if`` (``if_sugar._arm_readings``).
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


_PHI = """\
def f(x):
    if x is None:
        y = 1
    else:
        y = 2
    return y
"""

_NESTED = """\
def f(x, z):
    if x is None:
        if z is None:
            y = 1
        else:
            y = 2
    else:
        y = 3
    return y
"""


@pytest.mark.parametrize("source", [_PHI, _NESTED], ids=["phi", "nested"])
def test_no_post_after_the_if_reads_the_branch_slot(source: str) -> None:
    from sugar_lift_py_tests.floor.universe_value import UniverseValue
    from sugar_lift_py_tests.outcome import Completed

    outcome = _outcome(source, "f")
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


# ``(source, truthful value, lying values)``: each test reads ``f`` at an
# input every identity test of which is decided.
_TWINS = {
    "phi": (_PHI + "\n\ndef test_f():\n    assert f(None) == {v}\n", 1, (2,)),
    "nested": (
        _NESTED + "\n\ndef test_f():\n    assert f(None, None) == {v}\n",
        1,
        (2, 3),
    ),
    "one-armed": (
        "def f(x):\n"
        "    y = 2\n"
        "    if x is None:\n"
        "        y = 1\n"
        "    return y\n"
        "\n\ndef test_f():\n    assert f(None) == {v}\n",
        1,
        (2,),
    ),
}


@pytest.mark.parametrize("shape", sorted(_TWINS))
def test_the_truthful_half_is_sat(shape: str, tmp_path: Path) -> None:
    source, truthful, _lies = _TWINS[shape]
    result = run_source_through_real_solver(
        tmp_path / "t", source.format(v=truthful)
    )
    assert result.verdict == "sat"


@pytest.mark.parametrize(
    ("shape", "lie"),
    [(shape, lie) for shape in sorted(_TWINS) for lie in _TWINS[shape][2]],
)
def test_the_lying_half_is_never_sat(shape: str, lie: int, tmp_path: Path) -> None:
    # The phi selects by the test: for the input that takes the then arm,
    # the else arm's value is not satisfiable, whatever the slot's flag.
    source, _truthful, _lies = _TWINS[shape]
    result = run_source_through_real_solver(tmp_path / "l", source.format(v=lie))
    assert result.verdict != "sat"


def test_truth_of_a_formal_lie_is_never_sat(tmp_path: Path) -> None:
    # ``if c:`` over a formal: the phi reads the formal's truth, never a free
    # flag, so ``f(True) == 2`` is never satisfiable.
    source = (
        "def f(c):\n"
        "    if c:\n"
        "        x = 1\n"
        "    else:\n"
        "        x = 2\n"
        "    return x\n"
        "\n\ndef test_f():\n    assert f(True) == 2\n"
    )
    result = run_source_through_real_solver(tmp_path / "c", source)
    assert result.verdict != "sat"
