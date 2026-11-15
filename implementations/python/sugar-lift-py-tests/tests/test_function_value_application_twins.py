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
an append) is never read off the callee's body: the call takes the one
exposure rule every call takes, and on the call's completed face the
caller's cell reads ``python:after(<call result>, "cell:<name>")``, keyed on
the call (#7757 step 7).  The callee's contract states what it leaves in a
cell it rebinds over that term on each completed arm that ran to the body's
end (``UniverseValue.after_facts``), so the join decides a ``nonlocal``
rebinding, also one that stands after an early ``return``.  What an append
leaves in a cell whose type nothing decides is not stated, so that twin
stays ``open`` in both halves, never ``sat`` for the lie.
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

_NONLOCAL_REBOUND_AFTER_AN_EARLY_RETURN = """\
def test_count():
    n = 0

    def bump():
        nonlocal n
        if n > 5:
            return
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

# Decided before step 5 by following the callee's body; decided again at
# prove since the callee's contract states what it left in the cell it
# rebinds (``python:after(out, "cell:n")``, #7757 step 7).  After an early
# ``return`` the arm that ran on states it; the ordering ``n > 5`` over the
# cell's ``0`` is decided at prove (#8812), so the ``return`` arm is not
# taken.
_STATED_BY_THE_CALLEE = {
    "nonlocal-rebound": (_NONLOCAL_REBOUND_THROUGH_THE_VALUE, "1", "0"),
    "direct-nonlocal-rebound": (_DIRECT_NONLOCAL_REBOUND, "1", "0"),
    "nonlocal-rebound-after-an-early-return": (
        _NONLOCAL_REBOUND_AFTER_AN_EARLY_RETURN,
        "1",
        "0",
    ),
}

# Decided before step 5 by following the callee's body; ``open`` in both
# halves while the callee's contract states nothing of what it left in the
# cell: an append on a cell whose type nothing here decides is not
# determined by the contract's inputs (#7757 step 7).
_OPEN_UNTIL_STEP_7 = {
    "append-carried": (_APPEND_THROUGH_THE_VALUE, "1", "0"),
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
# that member was the one row owed in the cell and default twins.  Since
# #8743 the lift owes it and prove pays it at the join: its row stands in the
# proof, ``discharged`` ("answered: the joined contract ... decides
# python:compare.completes at this site"), and ``_owed`` reads only what is
# still owed after prove (scorecard 43745139407 measured the row so in all
# four shapes, the truthful halves ``sat`` and the lies ``unsat``).
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
    """Every ``undecided:`` row the source still owes after prove, by its
    property.  A member prove answered from a joined contract (status
    ``discharged``, reason ``answered: the joined contract ... decides ...``,
    ``members_answered_at_prove``) is owed by the lift and paid at the join:
    it is no debt of the source, and ``prove_verdict`` reads it so too."""
    return tuple(
        sorted(
            str(row.get("property"))
            for row in prove_doc.get("rows", [])
            if str(row.get("property") or "").startswith("undecided:")
            and row.get("status") != "discharged"
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


@pytest.mark.parametrize("shape", sorted(_STATED_BY_THE_CALLEE))
def test_a_cell_the_callee_rebinds_is_decided_by_its_contract(
    shape: str, tmp_path: Path
) -> None:
    source, true, false = _STATED_BY_THE_CALLEE[shape]
    truthful = run_source_through_real_solver(
        tmp_path / "t", source.format(claim=true)
    )
    lying = run_source_through_real_solver(tmp_path / "l", source.format(claim=false))
    print(
        json.dumps(
            {"truthful": truthful.verdict, "lying": lying.verdict}, sort_keys=True
        )
    )
    # The caller reads its cell after the call as the callee's contract
    # names it; the join decides it: the truthful claim is discharged and
    # the lying one refuted.  The callee's ``n += 1`` over its free input
    # may owe its operation, which keeps the truthful half from ``sat``.
    assert _claim_statuses(truthful.prove_doc) == ["discharged"], truthful.prove_doc
    assert truthful.verdict != "unsat", truthful.prove_doc
    assert lying.verdict == "unsat", lying.prove_doc


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
