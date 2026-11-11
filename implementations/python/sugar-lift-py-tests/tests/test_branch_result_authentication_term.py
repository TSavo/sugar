"""A branch-result testimony projects to the pair it proves equivalent.

A factory whose ``if`` reads an undecided condition returns a manager whose
prefix carries a ``BranchResultAuthentication``. The prefix is
content-addressed face by face, so the testimony needs a term: the slot guard
and the observed guard it stands for, and nothing else.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor.branch_result_coordinate import (
    BranchResultAuthentication,
    branch_result_guard,
)
from sugar_lift_py_tests.ir import _term_content_cid, ctor, formula_term, make_var, py_truthy
from sugar_source_tree.binding_state import BranchResultSlot


def _testimony(slot_id: str, var: str) -> BranchResultAuthentication:
    return BranchResultAuthentication(BranchResultSlot(slot_id), py_truthy(make_var(var)))


def test_term_is_the_slot_guard_and_the_observed_guard():
    testimony = _testimony("branch-result:a", "flag")
    term = testimony.to_term(owner="test")
    assert term == ctor(
        "python:branch_result_authentication",
        [
            formula_term(branch_result_guard(testimony.slot, None)),
            formula_term(py_truthy(make_var("flag"))),
        ],
    )


def test_equal_testimony_shares_a_cid_and_either_side_changes_it():
    same = _term_content_cid(_testimony("branch-result:a", "flag").to_term(owner="t"))
    assert same == _term_content_cid(_testimony("branch-result:a", "flag").to_term(owner="t"))
    assert same != _term_content_cid(_testimony("branch-result:b", "flag").to_term(owner="t"))
    assert same != _term_content_cid(_testimony("branch-result:a", "other").to_term(owner="t"))
