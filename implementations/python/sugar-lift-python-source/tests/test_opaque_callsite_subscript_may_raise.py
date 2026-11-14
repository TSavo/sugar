"""Subscripting an opaque call result may raise.

``textwrap.dedent("x")[0]``: the call's body is not projected, so its result
has no authenticated type and ``__getitem__`` dispatch is undecided. The
subscript used to complete as a bare ``py.subscript`` coordinate, which is a
claim that indexing never raises. It now completes only under the opaque
atom ``python:subscript.completes(<py.subscript term>)`` and halts with an
``UndeterminedRaiseEffect`` under its complement. It does not guess
IndexError/KeyError/TypeError and does not invent a member. A callsite whose
body floors keeps the floor's own decided subscript.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def _exits(tmp_path: Path, source: str):
    source_file = _open(_corpus(tmp_path, source))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return outcome_to_exitset(func.sugar().desugar())


def _owners(exits):
    return sorted(
        face.effect.producer_node_owner
        for face in exits.exits
        if isinstance(face, Halted) and isinstance(face.effect, UndeterminedRaiseEffect)
    )


def test_opaque_call_result_subscript_may_raise(tmp_path) -> None:
    exits = _exits(
        tmp_path, 'import textwrap\ndef f():\n    return textwrap.dedent("x")[0]\n'
    )
    assert _owners(exits) == [
        "CallSiteValue.subscript",
        "UnknownCallee:textwrap.dedent",
    ]
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    assert len(completed) == 1
    guard = repr(completed[0].guard)
    assert "python:unknown_callee_call.completes" in guard
    assert "python:subscript.completes" in guard
    assert "py.subscript" in repr(completed[0].value)


def test_subscript_halt_is_guarded_by_the_call_completing(tmp_path) -> None:
    exits = _exits(
        tmp_path, 'import textwrap\ndef f():\n    return textwrap.dedent("x")[0]\n'
    )
    (subscript_halt,) = [
        face
        for face in exits.exits
        if isinstance(face, Halted)
        and face.effect.producer_node_owner == "CallSiteValue.subscript"
    ]
    guard = repr(subscript_halt.guard)
    assert "python:unknown_callee_call.completes" in guard
    assert "python:subscript.completes" in guard


def test_floored_callsite_subscript_is_decided(tmp_path) -> None:
    exits = _exits(
        tmp_path, "def g():\n    return [1, 2]\ndef f():\n    return g()[0]\n"
    )
    assert _owners(exits) == []
    assert "python:subscript.completes" not in repr(exits)


def test_two_subscript_sites_get_distinct_atoms(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "import textwrap\ndef f():\n"
        '    s = textwrap.dedent("x")\n'
        "    a = s[0]\n"
        "    b = s[0]\n"
        "    return (a, b)\n",
    )
    halts = [
        face
        for face in exits.exits
        if isinstance(face, Halted)
        and face.effect.producer_node_owner == "CallSiteValue.subscript"
    ]
    assert len(halts) == 2
    assert halts[0].effect.occurrence != halts[1].effect.occurrence
    (completed,) = [face for face in exits.exits if isinstance(face, Completed)]
    guard = repr(completed.guard)
    assert guard.count("python:subscript.completes") == 2
    for halt in halts:
        assert halt.effect.occurrence in guard


def test_builtin_exception_subscript_stays_ground(tmp_path) -> None:
    exits = _exits(tmp_path, 'def f():\n    return ValueError("a")[0]\n')
    assert "python:subscript.completes" not in repr(exits)
    assert not [face for face in exits.exits if isinstance(face, Completed)]
    assert "CallSiteValue.subscript" not in _owners(exits)
