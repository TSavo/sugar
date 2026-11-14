"""A cited ``with`` carries every face to the function that contains it.

``with tarfile.open(p):`` cites a manager the lifter does not have: the head
call, ``__enter__`` and ``__exit__`` each complete opaque or raise
undetermined, and suppression of a body raise is undecided.  Every one of
those faces must reach the enclosing function, whatever the body does.

On main before this change, a body that always raised (``1/0``) left only the
body's ``ZeroDivisionError``: the cited sugar collapsed its faces to the
linear ``BlockValue`` view, and ``promote_raise_halts`` keeps a completed arm
only on fall-through, which a block ending in ``return`` does not have.  A
body that raised on one face lost the same faces and the face where it did
not raise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import ReturnValue, TermValue
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open

_BODIES = {
    "always-raises": "1/0",
    "raises-on-one-face": "if tarfile.DEFAULT_FORMAT:\n            raise ValueError(1)",
    "plain": "pass",
}


def _faces(tmp_path: Path, body: str):
    source = (
        "import tarfile\n"
        "def f(p):\n"
        "    with tarfile.open(p):\n"
        f"        {body}\n"
        "    return 7\n"
    )
    source_file = _open(_corpus(tmp_path, source))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return func.sugar().desugar()


def _effect_names(exits):
    return {
        type(face.effect).__name__ for face in exits.exits if isinstance(face, Halted)
    }


def _returns_seven(exits) -> bool:
    return any(
        isinstance(face, Completed)
        and any(
            isinstance(statement, ReturnValue) and statement.value == TermValue(7)
            for statement in face.value.record.statements
        )
        for face in exits.exits
    )


@pytest.mark.parametrize("shape", sorted(_BODIES))
def test_head_enter_exit_and_completion_faces_all_reach_the_function(
    tmp_path: Path, shape: str
) -> None:
    exits = _faces(tmp_path, _BODIES[shape])
    names = _effect_names(exits)
    # The head call may raise.
    assert any(
        isinstance(face, Halted)
        and isinstance(face.effect, UndeterminedRaiseEffect)
        and "UnknownCallee:tarfile.open" in str(face.effect)
        for face in exits.exits
    ), names
    # __enter__ and __exit__ may each raise.
    assert "ContextManagerEnterRuntimeEffect" in names
    assert "ContextManagerExitRuntimeEffect" in names
    # A completed face reaches ``return 7``: the body completed, or its raise
    # was suppressed by an exit result whose truth is undecided.
    assert _returns_seven(exits)


@pytest.mark.parametrize("shape", ["always-raises", "raises-on-one-face"])
def test_the_body_raise_is_kept_beside_its_suppressed_face(
    tmp_path: Path, shape: str
) -> None:
    exits = _faces(tmp_path, _BODIES[shape])
    assert any(
        isinstance(face, Halted) and isinstance(face.effect, RaiseEffect)
        for face in exits.exits
    )
    assert _returns_seven(exits)
