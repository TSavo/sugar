"""Solver twins: a read of a module attribute the import system set is lifted,
and the solver's answer is Python's (#7757, carry undecided).

``os.path.dirname(__file__)`` in a function, ``HERE = os.path.dirname(
__file__)`` at module level, ``getattr(__builtins__, '__dict__',
__builtins__)`` and ``__name__`` each left their reader over the free name,
and ``ScopedFormula`` refused the whole function or class by it (``illegal
free var(s): __file__``; pandas 13, numpy 23 and one ``__builtins__`` on the
nine-step lane, main 13e3413ad).  Each read is now the one undecided read of the attribute off
the module: no path, no module name and no ``NameError`` is decided.

What the claims may say: a claim that does not rest on the read is decided
as before, never refuted; a claim that rests on it (two reads of
``__file__`` compared) is not ``sat`` and not ``unsat`` by anything the
lifter decides.  A truthful claim is never ``unsat`` and a lying claim is
never ``sat``.  The refusal is gone from the proof.

Each twin goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    prove_verdict,
    run_source_through_real_solver,
)

_DELETED_REFUSAL = b"illegal free var"

# program -> (source with a ``{claim}`` hole, truthful claim, lying claim)
_PROGRAMS = {
    # The claim does not rest on the read.
    "file-in-a-function": (
        "import os\n\n\n"
        "def here():\n"
        "    return os.path.dirname(__file__)\n\n\n"
        "def test_f():\n"
        "    h = here()\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        "1",
        "2",
    ),
    "file-at-module-level": (
        "import os\n\n"
        "HERE = os.path.dirname(__file__)\n\n\n"
        "def test_f():\n"
        "    h = HERE\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        "1",
        "2",
    ),
    "builtins-through-getattr": (
        "def test_f():\n"
        "    b = getattr(__builtins__, '__dict__', __builtins__)\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        "1",
        "2",
    ),
    # The claim rests on the read: Python's answer is truthful (one module,
    # one ``__file__``), but the lifter decides no value for either read.
    "claim-on-two-file-reads": (
        "def test_f():\n"
        "    a = __file__\n"
        "    b = __file__\n"
        "    assert {claim}\n",
        "a == b",
        "a != b",
    ),
    "claim-on-the-module-name": (
        "def test_f():\n"
        "    name = __name__\n"
        "    assert {claim}\n",
        "name != 'builtins'",
        "name == 'builtins'",
    ),
}


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
@pytest.mark.parametrize("half", ["truthful", "lying"])
def test_a_module_attribute_read_is_lifted_and_honest(
    tmp_path: Path, program: str, half: str
) -> None:
    source, truthful, lying = _PROGRAMS[program]
    claim = truthful if half == "truthful" else lying
    project = tmp_path / program / half
    result = run_source_through_real_solver(project, source.replace("{claim}", claim))
    (proof,) = tuple(project.glob("*.proof"))
    assert _DELETED_REFUSAL not in proof.read_bytes(), (program, half)
    verdict = prove_verdict(result.prove_doc)
    if half == "truthful":
        assert verdict != "unsat", (program, result.prove_doc)
    else:
        assert verdict != "sat", (program, result.prove_doc)
