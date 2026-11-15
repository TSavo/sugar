"""Twins: what the module body's one run leaves unanswered is owed (#7757).

Step 8: what the proof does not decide, it states, as the one ``undecided``
member.  A module-level call nothing here answers (``X = make()`` with
``make`` imported) is that member, under the import door's target symbol, at
the call's site, exactly as the same call inside a function is
(``test_unanswered_call_member_twins``).

Two readers owe it.  A function that reads the value the call made (``X``)
reads it off the module run's completed arms, and owes every debt of those
arms (``call_site_sugar._module_end_value``); the file's scan states the
module run's own debts (``tree_enumerate.module_run_owed_calls``), so the
member is there even when no function reads what the call made.

Before this change the module run's debts were dropped where a function read
its value (the arms were rebuilt without ``owed``) and never packaged where
none did: the file minted a proof with nothing owed for ``make``, so the
truthful half of ``_UNREAD`` could read ``sat`` over an import whose call the
proof never stated.

Each twin goes through ``run_source_through_real_solver``: real ``sugar
mint`` then real ``sugar prove``.  A source that owes anything is never
``sat``; a lying claim is ``unsat`` whatever is owed.
"""

from __future__ import annotations

import json
from pathlib import Path

import cbor2

from sugar_lift_py_tests.witness_harness import (
    prove_verdict,
    run_source_through_real_solver,
)

# The test function reads the value the module-level call made.
_READ = (
    "from elsewhere import make\n\n"
    "X = make()\n\n\n"
    "def test_reads():\n"
    "    assert X == {claim}\n"
)
# No function reads what the module-level call made.
_UNREAD = (
    "from elsewhere import make\n\n"
    "make()\n\n\n"
    "def test_plain():\n"
    "    assert 1 + 1 == {claim}\n"
)
_CALL_LINE = 3


def _undecided_members(project: Path) -> list[dict]:
    """The header of every ``undecided`` member in the root proof."""
    (proof,) = tuple(project.glob("blake3-512_*.proof"))
    doc = cbor2.loads(proof.read_bytes())
    found = []
    for member in doc["members"].values():
        if isinstance(member, (bytes, bytearray)):
            member = json.loads(member)
        header = member.get("header") or {}
        if header.get("kind") == "undecided":
            found.append(header)
    return found


def _the_make_member(project: Path) -> dict:
    """The one member under ``make``'s target symbol: unanswered, at the
    module-level call."""
    (member,) = [
        header
        for header in _undecided_members(project)
        if header["symbol"] == "python:elsewhere.make"
    ]
    assert member["reason"] == {"unanswered": {}}, member
    assert member["site"]["file"] == "test_witness.py", member
    assert member["site"]["startLine"] == _CALL_LINE, member
    return member


def test_a_read_module_value_owes_the_module_call_in_both_halves(
    tmp_path: Path,
) -> None:
    # What ``make`` returns is not decided here, so neither claim is: both
    # halves are open, and both owe the module-level call under its symbol.
    for half, claim in (("truthful", 1), ("lying", 2)):
        project = tmp_path / half
        result = run_source_through_real_solver(project, _READ.format(claim=claim))
        _the_make_member(project)
        assert result.prove_doc["owed"] == len(_undecided_members(project))
        assert prove_verdict(result.prove_doc) == "open", (half, result.prove_doc)


def test_an_unread_module_call_is_owed_and_a_lie_is_still_caught(
    tmp_path: Path,
) -> None:
    truthful = run_source_through_real_solver(tmp_path / "t", _UNREAD.format(claim=2))
    lying = run_source_through_real_solver(tmp_path / "l", _UNREAD.format(claim=3))
    for project, result in ((tmp_path / "t", truthful), (tmp_path / "l", lying)):
        _the_make_member(project)
        assert result.prove_doc["owed"] == len(_undecided_members(project))
    # Owed is never green: the truthful half is open, not sat.
    assert prove_verdict(truthful.prove_doc) == "open", truthful.prove_doc
    assert prove_verdict(lying.prove_doc) == "unsat", lying.prove_doc
