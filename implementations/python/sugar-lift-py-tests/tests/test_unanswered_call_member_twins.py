"""Twins for PR B on #7766: a call nothing in the proof answers is one member.

Step 8: a Python call whose callee the lifter does not have is recorded once,
as an ``undecided`` member with ``reason: unanswered``, ``symbol`` the import
door's target symbol (an enrolled imported call) or ``null`` (Q5), and
``site`` the call's coordinate. The member records the call, never what
answers it, so it is the same staged or unstaged (row 0a.4). Step 9: until
prove joins it to an imported contract (PR C), prove owes it: ``undecidable``,
reason ``owed: no contract for <symbol> in this proof``. A source that owes
anything is never ``sat``; the truthful and the lying half both read ``open``.

The call is not the only thing such a source owes.  Its result is a value
whose type the lifter does not have, so the ``==`` applied to it is an
operation whose raise is not decided here either: the same two-faced outcome,
owing the same member kind at its own site, with no symbol
(``unanswered_calls``: "an undecided operand's dunder").  The call's member is
told from it by its symbol (an imported callee) or by its site (the call's own
span).

A local call is not this member: the callee's body is reduced at the call site
today (a second way, recorded as residue for item 26 / row 0a.3).  The local
callee's OWN proof has no caller, so its ``x + x`` over a formal is undecided
there and is owed by that proof, at the helper's line; the test function,
which applies the body to ``3``, owes nothing, and its claim is read by
``witness_harness.claim_verdict``.

Before this change (main, 72ef65bb1): the call left no record in the proof,
and its claim was refused as vacuous (``open``) or ``open`` by z3.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import cbor2

from sugar_lift_py_tests.witness_harness import (
    _stage_cli_project,
    _ensure_sugar_bin,
    claim_verdict,
    mint_project,
    prove_verdict,
    run_source_through_real_solver,
)

_IMPORTED = (
    "from idn import ident\n\n\ndef test_ident():\n    assert ident(3) == {claim}\n"
)
# A callee with no symbol that Python does not decide either: ``h`` is a name
# only a star import the lifter cannot read may bind.  (A name the module binds
# nowhere is not this: reading it raises ``NameError``, #7854.)
_UNBOUND = (
    "from unread_module import *\n\n\ndef test_h():\n    assert h() == {claim}\n"
)
_LOCAL = (
    "def double(x):\n    return x + x\n\n\n"
    "def test_double():\n    assert double(3) == {claim}\n"
)
_VENDOR = "def ident(x):\n    return x\n"


def _undecided_members(project: Path) -> dict[str, dict]:
    """Member CID -> header of every ``undecided`` member in the root proof."""
    (proof,) = tuple(project.glob("blake3-512_*.proof"))
    doc = cbor2.loads(proof.read_bytes())
    found = {}
    for cid, member in doc["members"].items():
        if isinstance(member, (bytes, bytearray)):
            member = json.loads(member)
        header = member.get("header") or {}
        if header.get("kind") == "undecided":
            found[cid] = header
    return found


def _symbol_members(members: dict[str, dict]) -> list[dict]:
    """The members that name a target symbol: calls the import door enrolled."""
    return [header for header in members.values() if header["symbol"] is not None]


def _symbolless_members(members: dict[str, dict]) -> list[dict]:
    """The members with no symbol: a call the import door does not name, or
    an operation on a value whose type the lifter does not have."""
    return [header for header in members.values() if header["symbol"] is None]


def _owed_rows(prove_doc: dict) -> list[dict]:
    return [
        row
        for row in prove_doc.get("rows") or []
        if str(row.get("property") or "").startswith("undecided:")
    ]


def test_an_imported_call_is_one_unanswered_member_owed_in_both_halves(
    tmp_path: Path,
) -> None:
    for half, claim in (("truthful", 3), ("lying", 4)):
        result = run_source_through_real_solver(
            tmp_path / half, _IMPORTED.format(claim=claim)
        )
        members = _undecided_members(tmp_path / half)
        # The call: the one member with a symbol, the import door's.
        (call,) = _symbol_members(members)
        assert call["symbol"] == "python:idn.ident"
        assert call["reason"] == {"unanswered": {}}
        assert call["site"]["file"] == "test_witness.py"
        assert call["site"]["startLine"] == 5
        # The ``==`` on the call's result: owed at its own site, no symbol.
        operations = _symbolless_members(members)
        assert operations, members
        for header in operations:
            assert header["reason"] == {"unanswered": {}}
            assert header["site"]["startLine"] == 5
        rows = _owed_rows(result.prove_doc)
        assert len(rows) == len(members)
        assert all(row["status"] == "undecidable" for row in rows)
        assert "owed: no contract for python:idn.ident in this proof" in {
            row["reason"] for row in rows
        }
        assert result.prove_doc["owed"] == len(members)
        assert prove_verdict(result.prove_doc) == "open", half


def test_a_call_with_no_symbol_is_a_member_with_symbol_null(tmp_path: Path) -> None:
    for half, claim in (("truthful", 3), ("lying", 4)):
        result = run_source_through_real_solver(
            tmp_path / half, _UNBOUND.format(claim=claim)
        )
        members = _undecided_members(tmp_path / half)
        assert members
        assert _symbol_members(members) == []
        for header in members.values():
            assert header["reason"] == {"unanswered": {}}
        # The call's own member sits at the call's span, ``h()`` on line 5.
        assert [
            header
            for header in members.values()
            if (
                header["site"]["startLine"],
                header["site"]["startCol"],
                header["site"]["endCol"],
            )
            == (5, 11, 14)
        ], members
        assert result.prove_doc["owed"] == len(members)
        assert prove_verdict(result.prove_doc) == "open", half


def test_a_local_call_is_not_an_unanswered_member(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(tmp_path / "t", _LOCAL.format(claim=6))
    lying = run_source_through_real_solver(tmp_path / "l", _LOCAL.format(claim=7))
    # ``def test_double`` is line 5; ``double`` and its ``x + x`` sit above it.
    test_line = 5
    for project, result in ((tmp_path / "t", truthful), (tmp_path / "l", lying)):
        members = _undecided_members(project)
        # Nothing is owed at or below the test function: the local call is
        # no member, and neither is anything applied to its decided result.
        # What is owed is ``double``'s own proof's ``x + x`` over its formal.
        assert _symbol_members(members) == []
        assert [header["site"]["startLine"] for header in members.values()] == [2]
        assert result.prove_doc["owed"] == 1
    assert claim_verdict(truthful.prove_doc, claims_from_line=test_line) == "sat"
    assert prove_verdict(lying.prove_doc) == "unsat"


def test_the_member_is_the_same_staged_and_unstaged(tmp_path: Path) -> None:
    """Row 0a.4: the call's member does not depend on what answers it."""
    sugar = _ensure_sugar_bin()
    consumer = tmp_path / "consumer"
    vendor = tmp_path / "vendor"
    _stage_cli_project(consumer, _IMPORTED.format(claim=3))
    _stage_cli_project(vendor, _VENDOR)
    (vendor / "test_witness.py").rename(vendor / "idn.py")

    def mint(project: Path) -> None:
        # The harness's one mint door: hermetic, stale proofs cleared first.
        result = mint_project(project, sugar_bin=sugar)
        assert result.returncode == 0, result.stderr

    mint(consumer)
    unstaged = _undecided_members(consumer)
    mint(consumer)
    again = _undecided_members(consumer)
    imports = consumer / ".sugar" / "imports"
    imports.mkdir(parents=True, exist_ok=True)
    mint(vendor)
    for vendor_proof in vendor.glob("blake3-512_*.proof"):
        shutil.copy(vendor_proof, imports / vendor_proof.name)
    assert tuple(imports.glob("*.proof")), "the vendor proof is staged"
    mint(consumer)
    staged = _undecided_members(consumer)
    (call,) = _symbol_members(unstaged)
    assert call["symbol"] == "python:idn.ident"
    assert unstaged == again == staged
    shutil.rmtree(imports)
