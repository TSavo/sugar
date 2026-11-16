"""Twins: a module global a same-file call mutates in place is read as the
callee's contract states it left it (#7757 step 7, #7661).

#9102 made a later call read a mutable global after a same-file call that
reaches it as ``python:after(<call result>, "global:G")``.  No contract
stated that term for a callee that mutates the global's object without
declaring it ``global`` (``def bump(): G[0] = 2``): the store was the
unanswered call, since a module global had no class input, so the caller's
read stayed free and both halves were ``open``.

A global some function of the module mutates through a dispatched call (a
method call on it, an item store or delete) now takes its class as an input,
``class:global:G`` (``nodes._receiver_class_globals``): the mutating callee
dispatches the call over it and states the object it left over
``python:after(out, "global:G")`` (``FunctionDef._cells_where_the_body_ends``);
every function that takes the global takes its class and hands it on
(``receiver_dispatch.global_class_arguments``); the row states it beside the
global's value (``call_site_sugar.stated_global_values``), bound at prove only
where the global is bound to that value (``consistency::bind_call``).  Prove
answers the dispatched store by the builtin ``list``'s law, and the reader's
join decides the claim.

The truthful claim is decided (its consistency row ``discharged``; the
mutating callee's own proof owes its store, so the whole verdict may be
``open``, never ``unsat``), and the lie is refuted.  Each half goes through
``run_source_through_real_solver``: real ``sugar mint`` then real ``sugar
prove``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_ITEM_STORE_THEN_A_READER = """\
G = [1, 2]


def bump():
    G[0] = 5


def h():
    return G[0]


def test_f():
    bump()
    assert h() == {claim}
"""

_APPEND_THEN_A_READER = """\
G = [0]


def add():
    G.append(7)


def h():
    return G[1]


def test_f():
    add()
    assert h() == {claim}
"""

# ``name: (source, truthful claim, lying claim)``.
_TWINS = {
    "item-store-then-a-reader": (_ITEM_STORE_THEN_A_READER, "5", "1"),
    "append-then-a-reader": (_APPEND_THEN_A_READER, "7", "0"),
}


def _claim_statuses(prove_doc: dict) -> list:
    """The status of each consistency row: the solver's verdict on the
    test's stated claim."""
    return [
        row.get("status")
        for row in prove_doc.get("rows", [])
        if str(row.get("property") or "").startswith("consistency:")
    ]


@pytest.mark.parametrize("shape", sorted(_TWINS))
def test_a_global_a_callee_mutates_in_place_is_read_as_it_left_it(
    shape: str, tmp_path: Path
) -> None:
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
    assert _claim_statuses(truthful.prove_doc) == ["discharged"], truthful.prove_doc
    assert truthful.verdict != "unsat", truthful.prove_doc
    assert lying.verdict == "unsat", lying.prove_doc
