"""Subscripting an opaque call result may raise.

``textwrap.dedent("x")[0]``: the call's body is not projected, so its result
has no authenticated type and ``__getitem__`` dispatch is undecided. The
subscript used to complete as a bare ``py.subscript`` coordinate, which is a
claim that indexing never raises. It is the one undecided read
(``FloorValue.undecided_subscript``, #7757 audit 2 row NEW-1, #9016): its
value is keyed per evaluation, ``python:subscript_result(<receiver>,
<index>, <key>)``, it completes only under
``python:subscript_op.completes(python:subscript_op(<result>, <key>))``,
and it halts with an ``UndeterminedRaiseEffect`` at the same key under the
complement. It does not guess IndexError/KeyError/TypeError and does not
invent a member. A callsite whose body floors keeps the floor's own decided
subscript.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open

_COMPLETES = "python:subscript_op.completes"
_RESULT = "python:subscript_result"
# The pre-#9016 spelling of the undecided read: nothing states it any more.
_RETIRED = "python:subscript.completes"


def _exits(tmp_path: Path, source: str):
    source_file = _open(_corpus(tmp_path, source))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return func.sugar().desugar()


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
    assert _COMPLETES in guard
    assert _RETIRED not in guard
    assert _RESULT in repr(completed[0].value)


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
    assert _COMPLETES in guard
    # The halt stands at the read's own key: the completes atom names it.
    assert subscript_halt.effect.occurrence in guard


def test_floored_callsite_subscript_is_decided(tmp_path) -> None:
    exits = _exits(
        tmp_path, "def g():\n    return [1, 2]\ndef f():\n    return g()[0]\n"
    )
    assert _owners(exits) == []
    assert _COMPLETES not in repr(exits)
    assert _RETIRED not in repr(exits)


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
    assert guard.count(_COMPLETES) == 2
    # Two evaluations of one read are two keys, so two values, never one term.
    for halt in halts:
        assert halt.effect.occurrence in guard


def test_builtin_exception_subscript_stays_ground(tmp_path) -> None:
    exits = _exits(tmp_path, 'def f():\n    return ValueError("a")[0]\n')
    assert _COMPLETES not in repr(exits)
    assert _RETIRED not in repr(exits)
    assert not [face for face in exits.exits if isinstance(face, Completed)]
    assert "CallSiteValue.subscript" not in _owners(exits)
