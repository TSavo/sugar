"""Twins for #7785: a function that reads a module-level name is owed, by name.

Plan row 7, steps 5 to 8. A function names ``LIMIT``, a module-level name: in
a claim (A, C), in its own return term (B, C's ``f``), or in the claim of one
function of several (D). The name is outside the scope the function's contract
declares (formals plus ``out``), so the scope law refuses that function, by
name, and every other function in the file mints. The proof carries one
``undecided`` member per refused function (symbol, site, reason); prove reads
the member from the ``.proof`` alone, reports it ``undecidable`` with reason
``owed: <owner>: <observed>``, counts ``owed``, and is never green while it
owes anything.

What a function sees of a module-level name is NOT decided here (the owner's
choice 2 on #7661 row 7). So a source whose claims belong to a refused
function reads ``open``, for the truthful and the lying half alike: never
``sat``, never ``unsat``.

Before this change (main, 7c129bef9) every shape failed at mint: the scope
law's panic killed the kit in the import round's preliminary fold
("fold claim tree failed: tree enumeration failed").

Each twin goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    prove_verdict,
    run_source_through_real_solver,
)

_OWED = "illegal free var(s): LIMIT"

_PROGRAMS = {
    # A. the name is an actual in the claim; f itself is in scope.
    "A": (
        "LIMIT = 10\n\n\ndef f(x):\n    return x + 1\n\n\n"
        "def test_f():\n    assert f(LIMIT) == {claim}\n",
        {"test_f"},
    ),
    # B. the name is in the callee's return term: f emits nothing else.
    "B": (
        "LIMIT = 10\n\n\ndef f(x):\n    return x + LIMIT\n\n\n"
        "def test_f():\n    assert f(1) == {claim}\n",
        {"f", "test_f"},
    ),
    # C. as B, and the name is in the claim too.
    "C": (
        "LIMIT = 10\n\n\ndef f(x):\n    return x + LIMIT\n\n\n"
        "def test_f():\n    assert f(1) == {limit_claim}\n",
        {"f", "test_f"},
    ),
}
_HALVES = {
    "truthful": {"claim": 11, "limit_claim": "LIMIT + 1"},
    "lying": {"claim": 12, "limit_claim": "LIMIT + 2"},
}

_CONTROL = (
    "def f(x):\n    return x + 10\n\n\ndef test_f():\n    assert f(1) == {claim}\n"
)

_MIXED = (
    "LIMIT = 10\n\n\ndef f(x):\n    return x + 10\n\n\n"
    "def test_plain():\n    assert f(1) == {claim}\n\n\n"
    "def test_reads():\n    assert LIMIT == 10\n"
)


def _function(symbol: str | None) -> str:
    """``python:<module>.<name>`` -> ``<name>``."""
    return str(symbol).rsplit(".", 1)[-1]


def _members(lift_doc: dict) -> dict[str, dict]:
    """Refused function -> its ``undecided`` row, as the kit sent it to mint."""
    return {
        _function(row.get("symbol")): row
        for row in lift_doc["ir"]
        if row.get("kind") == "undecided"
    }


def _owed_rows(prove_doc: dict) -> dict[str, dict]:
    """Owed function -> its prove row, read off the ``.proof`` by prove."""
    return {
        _function(row["property"].removeprefix("undecided:")): row
        for row in prove_doc.get("rows") or []
        if str(row.get("property") or "").startswith("undecided:")
    }


def _claim(prove_doc: dict, function: str) -> str | None:
    """The solver's verdict on one function's assertions, or None: no row."""
    statuses = [
        row.get("status")
        for row in prove_doc.get("rows") or []
        if row.get("property") == f"consistency:{function}"
    ]
    if not statuses:
        return None
    if "unsatisfied" in statuses:
        return "unsat"
    if all(status == "discharged" for status in statuses):
        return "sat"
    return "open"


def _assert_owed(project: Path, result, refused: set[str]) -> None:
    members = _members(result.lift_doc)
    assert set(members) == refused, members
    for name, member in members.items():
        assert member["reason"]["refused"]["observed"].endswith(_OWED), member
        assert member["site"]["file"], member
    owed = _owed_rows(result.prove_doc)
    assert set(owed) == refused, result.prove_doc.get("rows")
    for name, row in owed.items():
        assert row["status"] == "undecidable", row
        assert row["reason"].startswith("owed: "), row
        assert row["reason"].endswith(_OWED), row
        # Never decided: no claim of a refused function reached the solver.
        assert _claim(result.prove_doc, name) is None, row
    assert result.prove_doc["owed"] == len(refused)
    (proof,) = tuple(project.glob("*.proof"))
    assert _OWED.encode() in proof.read_bytes(), "the .proof carries the reason"


def test_control_without_a_module_level_name(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(tmp_path / "t", _CONTROL.format(claim=11))
    lying = run_source_through_real_solver(tmp_path / "l", _CONTROL.format(claim=12))
    for result in (truthful, lying):
        assert _members(result.lift_doc) == {}
        assert _owed_rows(result.prove_doc) == {}
        assert result.prove_doc["owed"] == 0
    assert prove_verdict(truthful.prove_doc) == "sat"
    assert prove_verdict(lying.prove_doc) == "unsat"


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
def test_a_function_reading_a_module_level_name_is_owed_by_name(
    tmp_path: Path, program: str
) -> None:
    source, refused = _PROGRAMS[program]
    for half, fill in _HALVES.items():
        project = tmp_path / half
        result = run_source_through_real_solver(project, source.format(**fill))
        _assert_owed(project, result, refused)
        assert prove_verdict(result.prove_doc) == "open", (half, result.prove_doc)


def test_one_refused_function_does_not_take_the_file(tmp_path: Path) -> None:
    """D: ``test_reads`` is owed by name; ``test_plain`` is still decided.

    The file as a whole is never ``sat`` while it owes ``test_reads``: the
    truthful half reads ``open``, the lying half ``unsat`` (``test_plain``'s
    lie is still caught).
    """
    truthful = run_source_through_real_solver(tmp_path / "t", _MIXED.format(claim=11))
    lying = run_source_through_real_solver(tmp_path / "l", _MIXED.format(claim=12))
    for project, result in ((tmp_path / "t", truthful), (tmp_path / "l", lying)):
        _assert_owed(project, result, {"test_reads"})
    assert _claim(truthful.prove_doc, "test_plain") == "sat"
    assert _claim(lying.prove_doc, "test_plain") == "unsat"
    assert prove_verdict(truthful.prove_doc) == "open"
    assert prove_verdict(lying.prove_doc) == "unsat"
