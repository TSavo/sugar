"""Twins for PR B on #7766: a call nothing in the proof answers is one member.

Step 8: a Python call whose callee the lifter does not have is recorded once,
as an ``undecided`` member with ``reason: unanswered``, ``symbol`` the import
door's target symbol (an enrolled imported call) or ``null`` (Q5), and
``site`` the call's coordinate. The member records the call, never what
answers it, so it is the same staged or unstaged (row 0a.4). Step 9: until
prove joins it to an imported contract (PR C), prove owes it: ``undecidable``,
reason ``owed: no contract for <symbol> in this proof``. A source that owes
anything is never ``sat``; the truthful and the lying half both read ``open``.

A local call is not this member: the callee's body is reduced at the call site
today (a second way, recorded as residue for item 26 / row 0a.3).

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
    prove_verdict,
    run_source_through_real_solver,
    run_sugar_cli,
)

_IMPORTED = (
    "from idn import ident\n\n\ndef test_ident():\n    assert ident(3) == {claim}\n"
)
_UNBOUND = "def test_h():\n    assert h() == {claim}\n"
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
        assert len(members) == 1, members
        (header,) = members.values()
        assert header["symbol"] == "python:idn.ident"
        assert header["reason"] == {"unanswered": {}}
        assert header["site"]["file"] == "test_witness.py"
        assert header["site"]["startLine"] == 5
        (row,) = _owed_rows(result.prove_doc)
        assert row["status"] == "undecidable"
        assert row["reason"] == "owed: no contract for python:idn.ident in this proof"
        assert result.prove_doc["owed"] == 1
        assert prove_verdict(result.prove_doc) == "open", half


def test_a_call_with_no_symbol_is_a_member_with_symbol_null(tmp_path: Path) -> None:
    for half, claim in (("truthful", 3), ("lying", 4)):
        result = run_source_through_real_solver(
            tmp_path / half, _UNBOUND.format(claim=claim)
        )
        (header,) = _undecided_members(tmp_path / half).values()
        assert header["symbol"] is None
        assert header["reason"] == {"unanswered": {}}
        assert header["site"]["startLine"] == 2
        assert result.prove_doc["owed"] == 1
        assert prove_verdict(result.prove_doc) == "open", half


def test_a_local_call_is_not_an_unanswered_member(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(tmp_path / "t", _LOCAL.format(claim=6))
    lying = run_source_through_real_solver(tmp_path / "l", _LOCAL.format(claim=7))
    for project, result in ((tmp_path / "t", truthful), (tmp_path / "l", lying)):
        assert _undecided_members(project) == {}
        assert result.prove_doc["owed"] == 0
    assert prove_verdict(truthful.prove_doc) == "sat"
    assert prove_verdict(lying.prove_doc) == "unsat"


def test_the_member_is_the_same_staged_and_unstaged(tmp_path: Path) -> None:
    """Row 0a.4: the call's member does not depend on what answers it."""
    sugar = _ensure_sugar_bin()
    consumer = tmp_path / "consumer"
    vendor = tmp_path / "vendor"
    _stage_cli_project(consumer, _IMPORTED.format(claim=3))
    _stage_cli_project(vendor, _VENDOR)
    (vendor / "test_witness.py").rename(vendor / "idn.py")

    def mint(project: Path, out: str = ".") -> None:
        if out == ".":
            for stale in project.glob("blake3-512_*.proof"):
                stale.unlink()
        result = run_sugar_cli(
            project, ["mint", "--out", out, "--quiet"], sugar_bin=sugar
        )
        assert result.returncode == 0, result.stderr

    mint(consumer)
    unstaged = _undecided_members(consumer)
    mint(consumer)
    again = _undecided_members(consumer)
    imports = consumer / ".sugar" / "imports"
    imports.mkdir(parents=True, exist_ok=True)
    mint(vendor, str(imports))
    assert tuple(imports.glob("*.proof")), "the vendor proof is staged"
    mint(consumer)
    staged = _undecided_members(consumer)
    assert len(unstaged) == 1
    assert unstaged == again == staged
    shutil.rmtree(imports)
