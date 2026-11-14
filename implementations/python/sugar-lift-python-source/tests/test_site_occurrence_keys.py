"""Each evaluation of a site is its own unknown: site keys carry the occurrence.

A concrete loop dissolves into one copy of its body per iteration, a list
comprehension into one copy of its element per member, and a source function's
body is reduced once per call. All of those copies share one source span, so
an opaque atom keyed on the span alone -- an unanswered call's completion, a
C call's completion and result, the exception an undetermined raise threw --
named ONE unknown for every evaluation: iteration 2's call was claimed to
complete exactly when iteration 1's did, and to return the same object.

Now every site key carries the dynamic occurrence path (each enclosing loop
iteration and callee frame), so each evaluation is its own atom. A site
evaluated once, outside any loop or callee frame, keeps its plain key.
"""

from __future__ import annotations

from pathlib import Path


from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.occurrence import occurrence_key, site_coordinate_cid

import itertools

from test_assignment_evaluates_rhs import _atoms, _holds, _rows
from test_undetermined_raise_except_matching import _exits

DEDENT = "UnknownCallee:textwrap.dedent"


def _halt_occurrences(rows):
    return sorted(
        payload.occurrence
        for kind, payload, _guard in rows
        if kind == "halt" and isinstance(payload, UndeterminedRaiseEffect)
    )


def _returns(rows):
    return [payload for kind, payload, _guard in rows if kind == "return"]


def _completion_atoms(rows):
    atoms = {}
    for _kind, _payload, guard in rows:
        _atoms(guard, atoms)
    return [
        atom for atom in atoms if atom.name == "python:unknown_callee_call.completes"
    ]


def _each_row_alone_reachable(rows):
    """Every row is the one exit of some world, and no world takes two."""
    atoms = {}
    for _kind, _payload, guard in rows:
        _atoms(guard, atoms)
    atoms = list(atoms)
    alone = set()
    for bits in itertools.product((False, True), repeat=len(atoms)):
        env = dict(zip(atoms, bits))
        taken = [i for i, (_k, _p, guard) in enumerate(rows) if _holds(guard, env)]
        assert len(taken) <= 1, taken
        alone.update(taken)
    assert alone == set(range(len(rows)))


def test_each_loop_iteration_calls_its_own_unknown(tmp_path: Path) -> None:
    source = (
        "import textwrap\n"
        "def f():\n"
        "    for i in range(2):\n"
        "        x = textwrap.dedent('a')\n"
        "    return x\n"
    )
    rows = _rows(_exits(tmp_path, source))
    halts = _halt_occurrences(rows)
    # Iteration 0 may raise, and iteration 1 may raise after iteration 0
    # completed: two halts, never one shared face.
    assert len(halts) == 2 and len(set(halts)) == 2
    assert all(h.endswith(("#0", "#1")) for h in halts)
    (returned,) = _returns(rows)
    # The loop's x is the result of the LAST evaluation, not the call spelling.
    assert isinstance(returned, CallSiteValue)
    assert returned.term.name == "python:call_result"
    # The evaluation is named by `python:occurrence(<site coordinate CID>,
    # <path>…)` (#7808): the last path segment is iteration 1.
    occurrence = returned.term.args[1]
    assert occurrence.name == "python:occurrence"
    assert occurrence.args[-1].value.endswith("#1")

    assert len(_completion_atoms(rows)) == 2
    # Three outcomes: raise in iteration 0, raise in iteration 1, return.
    assert len(rows) == 3
    _each_row_alone_reachable(rows)


def test_comprehension_members_are_not_claimed_equal(tmp_path: Path) -> None:
    source = (
        "import textwrap\n"
        "def f():\n"
        "    return [textwrap.dedent('a') for i in range(2)]\n"
    )
    rows = _rows(_exits(tmp_path, source))
    assert len(set(_halt_occurrences(rows))) == 2
    (returned,) = _returns(rows)
    assert isinstance(returned, ListValue)
    first, second = returned.elements
    assert first.to_term(owner="test") != second.to_term(owner="test")


def test_a_later_iteration_reads_the_earlier_iterations_value(tmp_path: Path) -> None:
    source = (
        "import textwrap\n"
        "def f():\n"
        "    x = 'z'\n"
        "    for i in range(2):\n"
        "        if i == 1:\n"
        "            return x\n"
        "        x = textwrap.dedent('a')\n"
        "    return 'never'\n"
    )
    rows = _rows(_exits(tmp_path, source))
    # Only iteration 0 evaluates the call; iteration 1 returns before it.
    (halt,) = _halt_occurrences(rows)
    assert halt.endswith("#0")
    (returned,) = _returns(rows)
    # Iteration 1 reads x before reassigning it: iteration 0's value, not a
    # fresh evaluation under iteration 1 and not the pre-loop 'z'.
    assert isinstance(returned, CallSiteValue)
    # The same evaluation, both parts of its identity checked against the
    # halt: the halt keeps `str(site)@path`; the call term names the same site
    # by coordinate and the same path (#7808).
    occurrence = returned.term.args[1]
    assert occurrence.name == "python:occurrence"
    path = tuple(arg.value for arg in occurrence.args[1:])
    # The halt key was built from this site under this path ...
    assert halt == occurrence_key(returned.site, path)
    # ... and the call term names that same site by its coordinate.
    assert occurrence.args[0].value == site_coordinate_cid(returned.site)


def test_nested_loops_key_every_iteration_pair(tmp_path: Path) -> None:
    source = (
        "import textwrap\n"
        "def f():\n"
        "    for i in range(2):\n"
        "        for j in range(2):\n"
        "            x = textwrap.dedent('a')\n"
        "    return x\n"
    )
    halts = _halt_occurrences(_rows(_exits(tmp_path, source)))
    assert len(halts) == 4 and len(set(halts)) == 4
    assert {h.rsplit("@", 1)[1].count("loop[") for h in halts} == {2}


def test_two_calls_of_one_helper_are_two_frames(tmp_path: Path) -> None:
    source = (
        "import textwrap\n"
        "def g():\n"
        "    return textwrap.dedent('a')\n"
        "def f():\n"
        "    a = g()\n"
        "    b = g()\n"
        "    return (a, b)\n"
    )
    rows = _rows(_exits(tmp_path, source))
    halts = _halt_occurrences(rows)
    # The dedent site inside g is evaluated once per call of g.
    assert len(halts) == 2 and len(set(halts)) == 2
    assert all("@call:" in h for h in halts)
    (returned,) = _returns(rows)
    assert isinstance(returned, TupleValue)

    assert len(_completion_atoms(rows)) == 2
    assert len(rows) == 3
    _each_row_alone_reachable(rows)


def test_a_c_call_in_a_loop_returns_one_result_per_iteration(tmp_path: Path) -> None:
    source = (
        "import decimal\n"
        "def f():\n"
        "    return [decimal.getcontext() for i in range(2)]\n"
    )
    rows = _rows(_exits(tmp_path, source))
    halts = [
        payload
        for kind, payload, _guard in rows
        if kind == "halt" and isinstance(payload, UndeterminedRaiseEffect)
    ]
    assert len({halt.occurrence for halt in halts}) == 2
    (returned,) = _returns(rows)
    first, second = returned.elements
    assert first.to_term(owner="test") != second.to_term(owner="test")


def test_a_site_evaluated_once_keeps_its_plain_key(tmp_path: Path) -> None:
    source = "import textwrap\ndef f():\n    return textwrap.dedent('a')\n"
    (halt,) = _halt_occurrences(_rows(_exits(tmp_path, source)))
    assert "@" not in halt
