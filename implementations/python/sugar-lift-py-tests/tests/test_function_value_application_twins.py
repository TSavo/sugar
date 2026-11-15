"""A call through a function's value applies it as a call by name does (#7757).

A local plain ``def`` binds its name to the function its statement built
(``nodes._binds_function_value``), and ``h = g; h()`` calls that value.  The
value's one application (``LambdaCallable.callable_application_with``) does
what a call by name of the ``def`` did:

- it reads each closure cell where the call stands (``Call._closure_cells``,
  ``CallableApplication.captured``): Python reads the cell when the body
  runs, so ``y = 2`` before ``h()`` is what ``g`` returns;
- what the body does to an object the caller sees reaches the caller through
  the one projection (``container_mutation.source_helper_actual_states``,
  ``call_site_value.caller_visible_values``): a ``nonlocal`` rebinding and an
  append are read after the call.

Before, the value's application carried no cell (refused by name) and the
caller's threading followed only a call spelled by name (the cell was
unknown after the call): neither half was decided.

A call by name of a plain ``def`` is that same application
(``Call._function_value_call``): no call seats a ``def``'s frame by its name
any more.  The direct twins below (a local ``def`` reading a cell, a module
``def`` binding its default, a ``*`` call) are decided through it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


_CELL_READ_AT_THE_CALL = """\
def test_cell():
    y = 1

    def g():
        return y

    h = g
    y = 2
    assert h() == {claim}
"""

_NONLOCAL_REBOUND_THROUGH_THE_VALUE = """\
def test_count():
    n = 0

    def bump():
        nonlocal n
        n += 1

    b = bump
    b()
    assert n == {claim}
"""

_APPEND_THROUGH_THE_VALUE = """\
def test_append():
    xs = []

    def add():
        xs.append(1)

    a = add
    a()
    assert len(xs) == {claim}
"""

_DIRECT_CELL_READ_AT_THE_CALL = """\
def test_cell():
    y = 1

    def g():
        return y

    y = 2
    assert g() == {claim}
"""

_DIRECT_NONLOCAL_REBOUND = """\
def test_count():
    n = 0

    def bump():
        nonlocal n
        n += 1

    bump()
    assert n == {claim}
"""

_MODULE_DEF_DEFAULT = """\
def f(a=3):
    return a


def test_default():
    assert f() == {claim}
"""

_MODULE_DEF_SPREAD = """\
def f(a, b):
    return a + b


def test_spread():
    t = (1, 2)
    assert f(*t) == {claim}
"""

_TWINS = {
    "cell-read-at-the-call": (_CELL_READ_AT_THE_CALL, "2", "1"),
    "nonlocal-rebound": (_NONLOCAL_REBOUND_THROUGH_THE_VALUE, "1", "0"),
    "append-carried": (_APPEND_THROUGH_THE_VALUE, "1", "0"),
    "direct-cell-read-at-the-call": (_DIRECT_CELL_READ_AT_THE_CALL, "2", "1"),
    "direct-nonlocal-rebound": (_DIRECT_NONLOCAL_REBOUND, "1", "0"),
    "module-def-default": (_MODULE_DEF_DEFAULT, "3", "4"),
    "module-def-spread": (_MODULE_DEF_SPREAD, "3", "4"),
}

# The called function's own contract (its body lifted alone, never the
# call's reduction) owes these rows (step 8): a nested ``def`` reading a cell
# of its enclosing function has that cell free (``return y``, ``nonlocal
# n``), and an operation on a formal nothing decides is unanswered
# (``xs.append(1)`` on the cell, ``a + b``).  A source that owes anything is
# never ``sat`` (``witness_harness.prove_verdict``), so the truthful half
# whose callee owes is ``open`` -- its claim decided all the same: the test's
# consistency row is discharged while the lying half's is refuted.
_OWED_BY_THE_CALLEE = {
    "cell-read-at-the-call": ("undecided:test_witness.py:4",),
    "nonlocal-rebound": ("undecided:test_witness.py:4",),
    "append-carried": ("undecided:test_witness.py:5",),
    "direct-cell-read-at-the-call": ("undecided:test_witness.py:4",),
    "direct-nonlocal-rebound": ("undecided:test_witness.py:4",),
    "module-def-default": (),
    "module-def-spread": ("undecided:test_witness.py:2",),
}


def _claim_statuses(prove_doc: dict) -> list:
    """The status of each consistency row: the solver's verdict on the
    test's stated claim."""
    return [
        row.get("status")
        for row in prove_doc.get("rows", [])
        if str(row.get("property") or "").startswith("consistency:")
    ]


def _owed(prove_doc: dict) -> tuple:
    """Every ``undecided:`` row the source owes, by its property."""
    return tuple(
        sorted(
            str(row.get("property"))
            for row in prove_doc.get("rows", [])
            if str(row.get("property") or "").startswith("undecided:")
        )
    )


@pytest.mark.parametrize("shape", sorted(_TWINS))
def test_a_call_through_the_value_is_decided(shape: str, tmp_path: Path) -> None:
    source, true, false = _TWINS[shape]
    truthful = run_source_through_real_solver(
        tmp_path / "t", source.format(claim=true)
    )
    lying = run_source_through_real_solver(tmp_path / "l", source.format(claim=false))
    print(
        json.dumps(
            {"truthful": truthful.verdict, "lying": lying.verdict}, sort_keys=True
        )
    )
    # The truthful claim is decided consistent, the lying one refuted.
    assert _claim_statuses(truthful.prove_doc) == ["discharged"], truthful.prove_doc
    assert lying.verdict == "unsat", lying.prove_doc
    # Nothing but the callee's own body is owed, and only that keeps the
    # truthful half from ``sat``.
    owed = _OWED_BY_THE_CALLEE[shape]
    assert _owed(truthful.prove_doc) == owed, truthful.prove_doc
    assert truthful.verdict == ("open" if owed else "sat"), truthful.prove_doc
