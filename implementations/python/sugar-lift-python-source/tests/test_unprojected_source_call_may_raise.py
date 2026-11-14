"""A consumer module's own call to a source-defined dependency is two-faced.

``textwrap.dedent`` resolves through the authenticated import graph to a
Python ``def`` in ``textwrap.py``. The consumer module's own call never had
that body projected at its site (frame projection runs only inside
dependency frames, and off-population sources are cited, not rebuilt), so
``return textwrap.dedent("x")`` lifted as a bodiless ``CallSiteValue`` with a
single Completed face: a claim that the call never raises. A body that was
not projected may raise anything. The call now completes as the same
``CallSiteValue`` only under ``python:source_call.completes`` and halts with
an ``UndeterminedRaiseEffect`` under its complement. Nothing about the
callee's behavior is invented; a call whose body IS projected is untouched.
Constructing an imported source-defined class is covered by
``test_source_class_construction_may_raise.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue
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


def _completes_under_source_call_atom(exits, name: str) -> bool:
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    return bool(completed) and all(
        "python:source_call.completes" in repr(face.guard)
        and f"value='{name}'" in repr(face.guard)
        for face in completed
    )


@pytest.mark.parametrize(
    "source",
    [
        'import textwrap\ndef f():\n    return textwrap.dedent("x")\n',
        'from textwrap import dedent\ndef f():\n    return dedent("x")\n',
        'import textwrap\ndef f():\n    textwrap.dedent("x")\n    return 1\n',
    ],
)
def test_unprojected_source_function_call_may_raise(tmp_path, source) -> None:
    exits = _exits(tmp_path, source)
    assert _owners(exits) == ["UnprojectedSourceCall:textwrap.dedent"]
    assert _completes_under_source_call_atom(exits, "dedent")


def test_completed_face_keeps_the_call_coordinate(tmp_path) -> None:
    exits = _exits(tmp_path, 'import textwrap\ndef f():\n    return textwrap.dedent("x")\n')
    assert "CallSiteValue(target_name='textwrap.dedent'" in repr(
        [face for face in exits.exits if isinstance(face, Completed)]
    )


def test_each_unprojected_call_site_has_its_own_raise_face(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        'import textwrap\ndef f():\n    textwrap.dedent("a")\n    return textwrap.dedent("b")\n',
    )
    halts = [face for face in exits.exits if isinstance(face, Halted)]
    assert len(halts) == 2
    assert len({face.effect.blame for face in halts}) == 2


def test_a_callee_with_no_source_is_not_asked_its_language(tmp_path) -> None:
    # ``decimal.getcontext`` has no Python body behind it: not bridged, the
    # one two-faced call to a callee the lifter does not have. No law keyed
    # on what the callee is written in answers it (#7757 item 3).
    exits = _exits(tmp_path, "import decimal\ndef f():\n    return decimal.getcontext()\n")
    owners = _owners(exits)
    assert len(owners) == 1
    assert not owners[0].startswith("LanguageOwned")


def test_local_function_call_is_not_floored(tmp_path) -> None:
    exits = _exits(tmp_path, "def g():\n    return 1\ndef f():\n    return g()\n")
    assert _owners(exits) == []
    assert all(isinstance(face, Completed) for face in exits.exits)
