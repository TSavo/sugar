"""A ``try``'s route is decided on each face it leaves by, never a free flag
(#7757, step 6).

A name bound on more than one route of a ``try`` is read after it through
the phi over the try's route slots (``Try._merge_completion_nets``,
``route_slot``).  Which route ran is not a flag the solver chooses: each
routed face is the body's completed arm or the handler that took a halt,
under that halt's own guard (``_route_one_halt``), and the face decides the
route slots in its own reduction context (``try_sugar._ground_route_on_faces``),
so the read after the ``try`` on that face takes that route's value.  A
route slot nothing on the path decided is read as the undecided member
(``branch_result_coordinate.undecided_slot_debt``, #8899).

Each twin raises under an identity test, which owes nothing, so the route
is decided by the test the halt is guarded by.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_TEST = "\n\ndef test_f():\n    assert f(None) == {v}\n"

# ``(source, truthful value, lying values)``, each read at ``f(None)``,
# which takes the handler route.
_TWINS = {
    "handler": (
        "def f(x):\n"
        "    r = 0\n"
        "    try:\n"
        "        r = 1\n"
        "        if x is None:\n"
        "            raise ValueError\n"
        "        r = 2\n"
        "    except ValueError:\n"
        "        r = 3\n"
        "    return r\n",
        3,
        (0, 1, 2),
    ),
    "else": (
        "def f(x):\n"
        "    try:\n"
        "        if x is None:\n"
        "            raise ValueError\n"
        "    except ValueError:\n"
        "        r = 3\n"
        "    else:\n"
        "        r = 2\n"
        "    return r\n",
        3,
        (2,),
    ),
    "finally": (
        "def f(x):\n"
        "    r = 0\n"
        "    try:\n"
        "        if x is None:\n"
        "            raise ValueError\n"
        "        r = 2\n"
        "    except ValueError:\n"
        "        r = 3\n"
        "    finally:\n"
        "        pass\n"
        "    return r\n",
        3,
        (0, 2),
    ),
}


@pytest.mark.parametrize("shape", sorted(_TWINS))
def test_the_truthful_half_is_never_refuted(shape: str, tmp_path: Path) -> None:
    source, truthful, _lies = _TWINS[shape]
    result = run_source_through_real_solver(
        tmp_path / "t", (source + _TEST).format(v=truthful)
    )
    assert result.verdict != "unsat"


@pytest.mark.parametrize(
    ("shape", "lie"),
    [(shape, lie) for shape in sorted(_TWINS) for lie in _TWINS[shape][2]],
)
def test_the_lying_half_is_never_sat(shape: str, lie: int, tmp_path: Path) -> None:
    # The handler route is the face the halt's guard (``x is None``) holds
    # on; no flag selects the body route's value there.
    source, _truthful, _lies = _TWINS[shape]
    result = run_source_through_real_solver(
        tmp_path / "l", (source + _TEST).format(v=lie)
    )
    assert result.verdict != "sat"
