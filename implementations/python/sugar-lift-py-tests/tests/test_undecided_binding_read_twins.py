"""Solver twins: a read of a name no one statement binds on every route is
lifted, and the solver's answer is Python's (#7757, carry undecided).

``if C: import pyarrow as pa``, ``if TYPE_CHECKING: import numba`` / ``else:
numba = import_optional_dependency("numba")``, ``try: import m`` / ``except
ImportError: pass`` and ``if C: def helper(): ...`` each left their reader
over the free name, and ``ScopedFormula`` refused the whole function by it
(``illegal free var(s): pa``; about 39 pandas functions on the nine-step
lane, run 43960179946).  Each read is now the join the threading builds: the
binding (the module, the call's result, the function) under the guard of the
route that bound it, and a ``NameError`` halt under the complement.

What the claims may say: the route is decided by nothing the test decides
(``idn.FLAG``, ``TYPE_CHECKING``), so a claim that rests on the read is not
``sat`` unless the read cannot change it; a truthful claim is never
``unsat`` and a lying claim is never ``sat``.  The refusal is gone from the
proof.

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

# program -> source with a ``{claim}`` hole
_PROGRAMS = {
    "conditional-import": (
        "import idn\n\n"
        "if idn.FLAG:\n"
        "    import pyarrow as pa\n\n\n"
        "def test_f():\n"
        "    m = pa\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
    "optional-dependency-call-result": (
        "from typing import TYPE_CHECKING\n\n"
        "from idn import import_optional_dependency\n\n\n"
        "def test_f():\n"
        "    if TYPE_CHECKING:\n"
        "        import numba\n"
        "    else:\n"
        "        numba = import_optional_dependency('numba')\n"
        "    jit = numba.jit\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
    "def-in-one-branch": (
        "import idn\n\n"
        "if idn.FLAG:\n\n"
        "    def helper():\n"
        "        return 1\n\n\n"
        "def test_f():\n"
        "    h = helper\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
    "try-import-gate": (
        "try:\n"
        "    import pyarrow as pa\n"
        "except ImportError:\n"
        "    pass\n\n\n"
        "def test_f():\n"
        "    m = pa\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
}
_HALVES = {"truthful": 1, "lying": 2}


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
def test_a_read_bound_on_some_routes_is_lifted_and_honest(
    tmp_path: Path, program: str
) -> None:
    source = _PROGRAMS[program]
    for half, claim in _HALVES.items():
        project = tmp_path / half
        result = run_source_through_real_solver(
            project, source.replace("{claim}", str(claim))
        )
        (proof,) = tuple(project.glob("*.proof"))
        assert _DELETED_REFUSAL not in proof.read_bytes(), (program, half)
        verdict = prove_verdict(result.prove_doc)
        if half == "truthful":
            assert verdict != "unsat", (program, result.prove_doc)
        else:
            assert verdict != "sat", (program, result.prove_doc)
