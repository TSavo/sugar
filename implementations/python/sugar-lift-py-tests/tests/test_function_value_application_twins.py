"""A call through a function's value is its coordinate and edge (#7757 step 5).

A local plain ``def`` binds its name to the function its statement built
(``nodes._binds_function_value``), and ``h = g; h()`` calls that value.  A
call of it, by name or through the value, is the call's coordinate with an
edge carrying the callee's join symbol, joined at prove exactly as an
imported call is (``LambdaCallable._edge_call``):

- the call reads each closure cell where the call stands
  (``Call._closure_cells``, ``CallableApplication.captured``) and supplies it
  as ``py.closure``: Python reads the cell when the body runs, so ``y = 2``
  before ``h()`` is what ``g`` returns, decided by the join;
- a parameter the call omits is supplied as ``py.default``, the value the
  ``def`` statement bound.

What the body does to an object the caller sees (a ``nonlocal`` rebinding,
an append) is no longer read off the callee's body: the call takes the one
exposure rule every unanswered call takes, so the caller's cell is unknown
after the call.  The callee's contract does not yet state its effects on
what it shares with its caller (step 7), so those twins are ``open`` in both
halves, never ``sat`` for the lie (decided before step 5, marked below).
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
    "direct-cell-read-at-the-call": (_DIRECT_CELL_READ_AT_THE_CALL, "2", "1"),
    "module-def-default": (_MODULE_DEF_DEFAULT, "3", "4"),
    "module-def-spread": (_MODULE_DEF_SPREAD, "3", "4"),
}

# Decided before step 5 by following the callee's body; ``open`` in both
# halves until the callee's contract states its effects on what it shares
# with its caller (step 7).
_OPEN_UNTIL_STEP_7 = {
    "nonlocal-rebound": (_NONLOCAL_REBOUND_THROUGH_THE_VALUE, "1", "0"),
    "append-carried": (_APPEND_THROUGH_THE_VALUE, "1", "0"),
    "direct-nonlocal-rebound": (_DIRECT_NONLOCAL_REBOUND, "1", "0"),
}

# The called function's own contract (its body lifted alone, never the
# call's reduction) owes these rows (step 8): an operation on a formal
# nothing decides is unanswered (``a + b``).  A source that owes anything is
# never ``sat`` (``witness_harness.prove_verdict``), so the truthful half
# whose callee owes is ``open`` -- its claim decided all the same: the test's
# consistency row is discharged while the lying half's is refuted.
#
# A nested ``def`` reading a cell of its enclosing function (``return y``)
# owes nothing since #8698: the cell is its contract's ``cell:y`` input, which
# the call supplies (``py.closure``).  The ``==`` on the call's result, at the
# test function's own line, is the one undecided equality over the call's
# result (#8743): prove answers it from the joined post, which decides its
# operands over literals (#8748).  On scorecard 43738710481 (before #8743)
# that member was the one row owed in the cell and default twins.
_OWED_BY_THE_CALLEE = {
    "cell-read-at-the-call": (),
    "direct-cell-read-at-the-call": (),
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


@pytest.mark.parametrize("shape", sorted(_OPEN_UNTIL_STEP_7))
def test_an_effect_of_a_same_file_call_is_open_until_its_contract_states_it(
    shape: str, tmp_path: Path
) -> None:
    source, true, false = _OPEN_UNTIL_STEP_7[shape]
    truthful = run_source_through_real_solver(
        tmp_path / "t", source.format(claim=true)
    )
    lying = run_source_through_real_solver(tmp_path / "l", source.format(claim=false))
    # The call is joined at prove; nothing it states says what it did to the
    # caller's cell, which the call left unknown: never ``sat`` for the lie.
    assert truthful.verdict == "open", truthful.prove_doc
    assert lying.verdict == "open", lying.prove_doc
