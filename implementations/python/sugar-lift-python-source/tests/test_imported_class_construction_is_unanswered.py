"""Constructing an imported class is an unanswered call.

``fractions.Fraction(1, 0)`` names an imported callee. Step 3: what that name
is gets answered only from the imported proofs, so no dependency source is
read to decide it is a ``class``. A class and a function are one law here: the
call completes as its call-site value only under
``python:unknown_callee_call.completes`` and halts with an
``UndeterminedRaiseEffect`` (owner ``UnknownCallee:<target>``) under its
complement, and both arms owe the call (``undecided``, reason
``unanswered``). No exception type is guessed. ``raise E(...)`` of an imported
exception class carries the call's halt beside the raise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
from sugar_lift_py_tests.unanswered_calls import owed_calls
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def _exits(tmp_path: Path, source: str):
    source_file = _open(_corpus(tmp_path, source))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return outcome_to_exitset(func.sugar().desugar())


def _undetermined(exits):
    return [
        face
        for face in exits.exits
        if isinstance(face, Halted) and isinstance(face.effect, UndeterminedRaiseEffect)
    ]


@pytest.mark.parametrize(
    "source",
    [
        "import fractions\ndef f():\n    return fractions.Fraction(1, 0)\n",
        "from fractions import Fraction\ndef f():\n    return Fraction(1, 0)\n",
    ],
)
def test_imported_class_construction_is_two_faced(tmp_path, source) -> None:
    exits = _exits(tmp_path, source)
    (halt,) = _undetermined(exits)
    assert halt.effect.producer_node_owner == "UnknownCallee:fractions.Fraction"
    assert halt.effect.exception_name is None
    guard = repr(halt.guard)
    assert "'not'" in guard and "python:unknown_callee_call.completes" in guard
    (completed,) = [face for face in exits.exits if isinstance(face, Completed)]
    assert "python:unknown_callee_call.completes" in repr(completed.guard)
    assert [call.symbol for call in owed_calls(exits)] == [
        "python:fractions.Fraction"
    ]


def test_construction_completed_face_keeps_the_callsite(tmp_path) -> None:
    exits = _exits(
        tmp_path, "import fractions\ndef f():\n    return fractions.Fraction(1, 2)\n"
    )
    (completed,) = [face for face in exits.exits if isinstance(face, Completed)]
    assert "Fraction" in repr(completed.value)
    assert len(_undetermined(exits)) == 1


def test_two_constructions_get_distinct_atoms(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "import fractions\ndef f():\n"
        "    return (fractions.Fraction(1, 2), fractions.Fraction(1, 2))\n",
    )
    halts = _undetermined(exits)
    assert len(halts) == 2
    assert halts[0].effect.occurrence != halts[1].effect.occurrence


def test_raising_an_imported_exception_class_keeps_its_call_halt(
    tmp_path,
) -> None:
    exits = _exits(
        tmp_path,
        'import json\ndef f():\n    raise json.JSONDecodeError("m", "d", 0)\n',
    )
    assert not [face for face in exits.exits if isinstance(face, Completed)]
    (construction,) = _undetermined(exits)
    assert construction.effect.producer_node_owner == (
        "UnknownCallee:json.JSONDecodeError"
    )
    raised = [
        face
        for face in exits.exits
        if isinstance(face, Halted) and isinstance(face.effect, RaiseEffect)
    ]
    assert len(raised) == 1
    assert "python:unknown_callee_call.completes" in repr(raised[0].guard)


def test_raise_after_construction_carries_the_statement_prefix(tmp_path) -> None:
    # ``raise E(...)`` is a simple statement: it binds nothing before its own
    # halt, so the raise arm sequenced after the call's completing arm carries
    # the block's prefix as its pre-halt state, exactly as a plain
    # ``Incomplete`` raise does. A boundary that consumes it needs that record.
    exits = _exits(
        tmp_path,
        'import json\ndef f():\n    raise json.JSONDecodeError("m", "d", 0)\n',
    )
    raised = [
        face
        for face in exits.exits
        if isinstance(face, Halted) and isinstance(face.effect, RaiseEffect)
    ]
    assert len(raised) == 1
    assert raised[0].state is not None
