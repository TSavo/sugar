"""A consumer module's own call to an imported callee is unanswered.

Step 3: an imported name is answered only from the imported proofs in
``.sugar/imports/``; no dependency source is read to decide what it is. So
``return textwrap.dedent("x")`` is a call nothing in this proof answers: it
completes as the call-site value only under
``python:unknown_callee_call.completes``, halts with an
``UndeterminedRaiseEffect`` under its complement, and both arms owe the call
as the proof's ``undecided`` member (reason ``unanswered``) under the import
table's target symbol. Nothing about the callee's behavior is invented, and
the call is never a total completion.

Before #7757 item 6 the installed ``textwrap.py`` was read with stdlib ``ast``
to decide that ``dedent`` is a ``def``, and that face owed nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_lift_py_tests.unanswered_calls import owed_calls
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open


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


def _completes_under_unanswered_atom(exits, name: str) -> bool:
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    return bool(completed) and all(
        "python:unknown_callee_call.completes" in repr(face.guard)
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
def test_imported_function_call_is_unanswered(tmp_path, source) -> None:
    exits = _exits(tmp_path, source)
    assert _owners(exits) == ["UnknownCallee:textwrap.dedent"]
    assert _completes_under_unanswered_atom(exits, "textwrap.dedent")
    assert [call.symbol for call in owed_calls(exits)] == ["python:textwrap.dedent"]


def test_completed_face_keeps_the_call_coordinate(tmp_path) -> None:
    exits = _exits(tmp_path, 'import textwrap\ndef f():\n    return textwrap.dedent("x")\n')
    assert "CallSiteValue(target_name='textwrap.dedent'" in repr(
        [face for face in exits.exits if isinstance(face, Completed)]
    )


def test_each_unanswered_call_site_has_its_own_raise_face(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        'import textwrap\ndef f():\n    textwrap.dedent("a")\n    return textwrap.dedent("b")\n',
    )
    halts = [face for face in exits.exits if isinstance(face, Halted)]
    assert len(halts) == 2
    assert len({face.effect.blame for face in halts}) == 2
    assert len(owed_calls(exits)) == 2


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
