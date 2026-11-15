"""Twins: a function that reads a module-level name bound to a ground literal.

These were the #7785 twins: a function naming ``LIMIT`` was refused by the
scope law, by name ("illegal free var(s): LIMIT"). That refusal is gone.
Item 7 of #7757 reads a module global through its key (#7945, #7956, #7971),
and a function reduced on its own binds its module-final keys at frame entry
where the final write assigned a ground immutable literal (#8018, #8024). So
``LIMIT = 10`` is read as ``10`` in ``f``, in ``test_f`` and in ``test_reads``,
and every claim below reaches the solver. Python's answer is the solver's:
each truthful claim holds, each lying claim does not.

What a proof still owes here is not the name. ``f`` reduced as its own proof
has no caller, so its operation on its formal ``x`` (``x + 1``, ``x + LIMIT``,
``x + 10``) is the two-faced arm for an absent actual, owing one ``undecided``
member (reason ``unanswered``, symbol ``None``) at the operation's site
(#8176). #8176 named that verdict change as waiting on the owner's word (the
alternative: a function's own operation on its formal is parametric and owes
nothing). These twins do not decide it: the only member a source may owe is
that one, at ``f``'s operation, and the truthful file verdict is read off it
(``open`` while it is owed, ``sat`` when nothing is). A source with anything
owed is never ``sat``; a lying claim is ``unsat`` either way.

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

_DELETED_REFUSAL = b"illegal free var"

# program -> (source, the functions whose claims the solver decides, the line
# of f's one operation on its formal)
_PROGRAMS = {
    # A. the name is an actual in the claim.
    "A": (
        "LIMIT = 10\n\n\ndef f(x):\n    return x + 1\n\n\n"
        "def test_f():\n    assert f(LIMIT) == {claim}\n",
        {"test_f"},
        5,
    ),
    # B. the name is in the callee's return term.
    "B": (
        "LIMIT = 10\n\n\ndef f(x):\n    return x + LIMIT\n\n\n"
        "def test_f():\n    assert f(1) == {claim}\n",
        {"test_f"},
        5,
    ),
    # C. as B, and the name is in the claim too.
    "C": (
        "LIMIT = 10\n\n\ndef f(x):\n    return x + LIMIT\n\n\n"
        "def test_f():\n    assert f(1) == {limit_claim}\n",
        {"test_f"},
        5,
    ),
}
_HALVES = {
    "truthful": {"claim": 11, "limit_claim": "LIMIT + 1"},
    "lying": {"claim": 12, "limit_claim": "LIMIT + 2"},
}

_CONTROL = (
    "def f(x):\n    return x + 10\n\n\ndef test_f():\n    assert f(1) == {claim}\n"
)
_CONTROL_OPERATION_LINE = 2

_MIXED = (
    "LIMIT = 10\n\n\ndef f(x):\n    return x + 10\n\n\n"
    "def test_plain():\n    assert f(1) == {claim}\n\n\n"
    "def test_reads():\n    assert LIMIT == 10\n"
)
_MIXED_OPERATION_LINE = 5


def _members(lift_doc: dict) -> list[dict]:
    """Every ``undecided`` row, as the kit sent it to mint."""
    return [row for row in lift_doc["ir"] if row.get("kind") == "undecided"]


def _owed_rows(prove_doc: dict) -> list[dict]:
    """Every prove row read off an ``undecided`` member of the ``.proof``."""
    return [
        row
        for row in prove_doc.get("rows") or []
        if str(row.get("property") or "").startswith("undecided:")
    ]


def _claim(prove_doc: dict, function: str) -> str | None:
    """The solver's verdict on one function's assertions, or None: no row."""
    statuses = [
        row.get("status")
        for row in prove_doc.get("rows") or []
        if row.get("property") == f"consistency:python:test_witness.{function}"
    ]
    if not statuses:
        return None
    if "unsatisfied" in statuses:
        return "unsat"
    if all(status == "discharged" for status in statuses):
        return "sat"
    return "open"


_CALLEE = "python:test_witness.f"


def _assert_read_not_refused(
    project: Path, result, decided: set[str], half: str, operation_line: int
) -> list[dict]:
    """No function is refused for the name; every claim is decided by Python.

    The only member a source may owe is ``f``'s own operation on its formal
    (#8176): one ``unanswered`` row, symbol ``None``, at that line.  A call
    of ``f`` is its coordinate and an edge joined at prove (#7757 step 5):
    the lift states it as a member with ``f``'s join symbol, and an
    operation on its result as a member with none; prove joins ``f``'s
    contract and answers both, so neither is owed.  Returns the members
    the source owes after prove.
    """
    members = _members(result.lift_doc)
    for member in members:
        assert member["reason"] == {"unanswered": {}}, member
        assert member["site"]["file"], member
        assert member["symbol"] in (None, _CALLEE), member
    own = [
        member
        for member in members
        if member["symbol"] is None and member["site"]["startLine"] == operation_line
    ]
    assert len(own) <= 1, members
    owed = [row for row in _owed_rows(result.prove_doc) if row["status"] != "discharged"]
    assert len(owed) == len(own), result.prove_doc.get("rows")
    for row in owed:
        assert row["status"] == "undecidable", row
        assert row["reason"].startswith("owed: no contract for "), row
        assert row["line"] == operation_line, row
    for row in _owed_rows(result.prove_doc):
        if row["status"] == "discharged":
            assert row["reason"].startswith("answered: "), row
    assert result.prove_doc["owed"] == len(own)
    expected = "sat" if half == "truthful" else "unsat"
    for function in decided:
        assert _claim(result.prove_doc, function) == expected, (
            function,
            result.prove_doc.get("rows"),
        )
    (proof,) = tuple(project.glob("*.proof"))
    assert _DELETED_REFUSAL not in proof.read_bytes(), "no name is refused"
    return owed


def _file_verdict(owed: list[dict], half: str) -> str:
    """Owed is never green; a lying claim is unsat whatever is owed."""
    if half == "lying":
        return "unsat"
    return "open" if owed else "sat"


def test_control_without_a_module_level_name(tmp_path: Path) -> None:
    for half, claim in (("truthful", 11), ("lying", 12)):
        project = tmp_path / half
        result = run_source_through_real_solver(project, _CONTROL.format(claim=claim))
        members = _assert_read_not_refused(
            project, result, {"test_f"}, half, _CONTROL_OPERATION_LINE
        )
        assert prove_verdict(result.prove_doc) == _file_verdict(members, half)


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
def test_a_function_reading_a_module_level_name_reads_its_value(
    tmp_path: Path, program: str
) -> None:
    source, decided, operation_line = _PROGRAMS[program]
    for half, fill in _HALVES.items():
        project = tmp_path / half
        result = run_source_through_real_solver(project, source.format(**fill))
        members = _assert_read_not_refused(
            project, result, decided, half, operation_line
        )
        assert prove_verdict(result.prove_doc) == _file_verdict(members, half), (
            half,
            result.prove_doc,
        )


def test_a_function_reading_a_module_level_name_beside_another_is_decided(
    tmp_path: Path,
) -> None:
    """D: ``test_reads`` reads ``LIMIT == 10`` and is decided beside ``test_plain``.

    Truthful: both claims hold. Lying: ``test_plain``'s lie is caught.
    ``test_reads`` asserts the same truth in both halves.
    """
    truthful = run_source_through_real_solver(tmp_path / "t", _MIXED.format(claim=11))
    lying = run_source_through_real_solver(tmp_path / "l", _MIXED.format(claim=12))
    truthful_members = _assert_read_not_refused(
        tmp_path / "t",
        truthful,
        {"test_plain", "test_reads"},
        "truthful",
        _MIXED_OPERATION_LINE,
    )
    lying_members = _assert_read_not_refused(
        tmp_path / "l", lying, {"test_plain"}, "lying", _MIXED_OPERATION_LINE
    )
    assert _claim(lying.prove_doc, "test_reads") == "sat"
    assert prove_verdict(truthful.prove_doc) == _file_verdict(
        truthful_members, "truthful"
    )
    assert prove_verdict(lying.prove_doc) == _file_verdict(lying_members, "lying")
