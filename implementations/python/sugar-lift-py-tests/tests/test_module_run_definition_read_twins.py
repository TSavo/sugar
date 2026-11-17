"""Solver twins: a module ``def`` or ``class`` read as a value by the module's
own run is lifted, and the solver's answer is Python's (#7757).

``ALIAS = helper``, ``SIZE = Box.size`` and a class body's ``observance =
double`` each left the module run reading the free name (``helper``, ``Box``,
``double``): the run bound a ``def``/``class`` name only for a reader outside
the module block, and ``ScopedFormula`` refused every function reading the
run by it (``illegal free var(s): helper``; about 200 pandas and numpy
functions and classes on the 13e3413ad nine-step lane:
``get_resampler.__doc__ = ...``, ``Rolling.__doc__ = Window.__doc__``,
``@doc(IndexingMixin.loc)``, ``(_in, _not_in)``, ``tensordot.__doc__ =
...``).  Each read is now the value the statement bound, under its key.

What the claims may say: a truthful claim is never ``unsat`` and a lying
claim is never ``sat``; the refusal is gone from the proof.

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
    "plain-def-alias": (
        "def helper():\n"
        "    return 1\n\n\n"
        "ALIAS = helper\n\n\n"
        "def test_f():\n"
        "    f = ALIAS\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        1,
        2,
    ),
    "class-attribute": (
        "class Box:\n"
        "    size = 1\n\n\n"
        "SIZE = Box.size\n\n\n"
        "def test_f():\n"
        "    assert SIZE == {claim}\n",
        1,
        2,
    ),
    "class-body-reads-a-module-def": (
        "def double(x):\n"
        "    return 2 * x\n\n\n"
        "class Rule:\n"
        "    observance = double\n"
        "    size = 3\n\n\n"
        "def test_f():\n"
        "    assert Rule.size == {claim}\n",
        3,
        4,
    ),
    "plain-def-doc-store": (
        "def helper():\n"
        "    return 1\n\n\n"
        "helper.__doc__ = 'one'\n"
        "LIMIT = 5\n\n\n"
        "def test_f():\n"
        "    assert LIMIT == {claim}\n",
        5,
        6,
    ),
}


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
def test_a_module_run_read_of_a_definition_is_lifted_and_honest(
    tmp_path: Path, program: str
) -> None:
    source, truthful, lying = _PROGRAMS[program]
    for half, claim in (("truthful", truthful), ("lying", lying)):
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
