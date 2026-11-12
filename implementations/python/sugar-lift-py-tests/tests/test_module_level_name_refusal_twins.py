"""Twins for #7785: a function that reads a module-level name is refused by name.

Plan row 7, steps 5 to 7. A row of a function names ``LIMIT``, a module-level
name: in a claim (A, C), in a callee's return term the floor reduces into the
claim (B), or in the claim of one function of several (D). The row is outside
the scope its contract declares (formals plus ``out``), so the scope law
refuses it. Before this fix the refusal killed the kit and ``sugar mint``
failed for the whole file. Now that one function is refused by name, the
refusal names the free variable, and every other function in the file mints.

What a function sees of a module-level name is NOT decided here (the owner's
choice 2 on #7661 row 7). So the reading function's claim is never ``sat`` and
never ``unsat``: it is a named refusal, for the truthful and the lying half.

Each twin goes through real ``sugar mint`` and real ``sugar prove``. The mint
report is ``sugar mint --json``: its ``lift.diagnostics`` carries the refusal
with the refused function as ``item``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    _ensure_sugar_bin,
    _stage_cli_project,
    clear_stale_project_proofs,
    run_sugar_cli,
)

_PROGRAMS = {
    # A. the name is an actual in the claim.
    "A": (
        "LIMIT = 10\n\n\ndef f(x):\n    return x + 1\n\n\n"
        "def test_f():\n    assert f(LIMIT) == {claim}\n"
    ),
    # B. the name is in the callee's return term.
    "B": (
        "LIMIT = 10\n\n\ndef f(x):\n    return x + LIMIT\n\n\n"
        "def test_f():\n    assert f(1) == {claim}\n"
    ),
    # C. as B, and the name is in the claim too.
    "C": (
        "LIMIT = 10\n\n\ndef f(x):\n    return x + LIMIT\n\n\n"
        "def test_f():\n    assert f(1) == {limit_claim}\n"
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


def _mint_and_prove(project: Path, source: str) -> tuple[dict, dict]:
    """Real mint (``--json``, the mint report) then real prove."""
    sugar = _ensure_sugar_bin()
    _stage_cli_project(project, source)
    clear_stale_project_proofs(project)
    mint = run_sugar_cli(project, ["mint", "--out", ".", "--json"], sugar_bin=sugar)
    assert mint.returncode == 0, f"mint failed\n{mint.stdout}\n{mint.stderr}"
    report = json.loads(mint.stdout[mint.stdout.index("\n{") + 1 :])
    prove = run_sugar_cli(
        project, ["prove", ".", "--json", "--z3", "z3"], sugar_bin=sugar
    )
    assert prove.stdout.strip(), f"prove failed loudly\n{prove.stderr}"
    return report, json.loads(prove.stdout)


def _refusals(report: dict) -> dict[str, str]:
    """Refused function -> the refusal, read off the mint report."""
    return {
        diagnostic["item"]: diagnostic["reason"]
        for diagnostic in report["lift"].get("diagnostics") or []
        if isinstance(diagnostic, dict) and diagnostic.get("item")
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


def test_control_without_a_module_level_name(tmp_path: Path) -> None:
    truthful = _mint_and_prove(tmp_path / "t", _CONTROL.format(claim=11))
    lying = _mint_and_prove(tmp_path / "l", _CONTROL.format(claim=12))
    for report, _prove in (truthful, lying):
        assert _refusals(report) == {}
    assert _claim(truthful[1], "test_f") == "sat"
    assert _claim(lying[1], "test_f") == "unsat"


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
def test_a_function_reading_a_module_level_name_is_refused_by_name(
    tmp_path: Path, program: str
) -> None:
    for half, fill in _HALVES.items():
        report, prove_doc = _mint_and_prove(
            tmp_path / half, _PROGRAMS[program].format(**fill)
        )
        refusals = _refusals(report)
        assert "test_f" in refusals, (half, refusals)
        assert "illegal free var(s): LIMIT" in refusals["test_f"], (half, refusals)
        # Never decided: no claim of test_f reached the solver as sat or unsat.
        assert _claim(prove_doc, "test_f") is None, (half, prove_doc.get("rows"))


def test_one_refused_function_does_not_take_the_file(tmp_path: Path) -> None:
    """D: ``test_reads`` is refused by name; ``test_plain`` is still decided."""
    truthful = _mint_and_prove(tmp_path / "t", _MIXED.format(claim=11))
    lying = _mint_and_prove(tmp_path / "l", _MIXED.format(claim=12))
    for report, prove_doc in (truthful, lying):
        refusals = _refusals(report)
        assert set(refusals) == {"test_reads"}, refusals
        assert "illegal free var(s): LIMIT" in refusals["test_reads"]
        assert _claim(prove_doc, "test_reads") is None
    assert _claim(truthful[1], "test_plain") == "sat"
    assert _claim(lying[1], "test_plain") == "unsat"


def test_the_proof_carries_the_refusal(tmp_path: Path) -> None:
    """RED: the ``.proof`` does not carry the refusal.

    The mint report names it; the sealed ``.proof`` holds nothing for
    ``test_f`` and nothing that says why, so the proof read alone cannot tell a
    refused claim from an absent one. How a proof carries a refused claim (a
    row kind, a sealed field) is a proof-format decision that is not made
    here. Plain failing test: green when the proof carries it.
    """
    report, _prove = _mint_and_prove(tmp_path, _PROGRAMS["A"].format(claim=11))
    assert "test_f" in _refusals(report)
    (proof,) = tuple(tmp_path.glob("*.proof"))
    assert b"illegal free var(s): LIMIT" in proof.read_bytes()
