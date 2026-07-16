# SPDX-License-Identifier: MIT OR Apache-2.0
"""Sat/unsat witnesses for CallSiteValue binary dispatch (+ dig fold).

Witnesses are truthful/lying twins. CallSiteValue.add digs or EUF-joins; when
body dig folds `g(2) + 1` the function post is ground `out = 3` — that face is
what the twins discriminate on.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.sugar.add_op_sugar import AddOpSugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_DIG_PREFIX = "def g(x):\n" "    return x\n" "def A():\n" "    return g(2) + 1\n" "\n"

_TRUTHFUL = _DIG_PREFIX + "def test_a():\n    assert A() == 3\n"
_LYING = _DIG_PREFIX + "def test_a():\n    assert A() == 4\n"

_DUAL = (
    _DIG_PREFIX
    + "def test_dual():\n"
    + "    assert A() == 3\n"
    + "    assert A() == 4\n"
)


def test_add_op_sugar_registers_callsite_add_dig_witness() -> None:
    raw = AddOpSugar.witnesses()
    pairs = raw if isinstance(raw, tuple) else (raw,)
    assert any(
        isinstance(p, SugarWitnessPair) and p.name == "callsite_add_dig_return"
        for p in pairs
    )
    dig = next(p for p in pairs if p.name == "callsite_add_dig_return")
    assert dig.truthful.expected == "sat"
    assert dig.lying.expected == "unsat"
    assert dig.owner_sugar == "AddOpSugar"
    assert dig.family == "callsite-binary-dig"


def test_callsite_add_dig_folds_post_to_ground_three() -> None:
    """Body dig + CallSiteValue.add must ground `A` post to out = 3."""
    rpc = lift_file_payload(_TRUTHFUL, "t.py").to_rpc()
    a = next(r for r in rpc["ir"] if r.get("name") == "A")
    post = a["post"]
    assert post["kind"] == "atomic" and post["name"] == "="
    rhs = post["args"][1]
    assert rhs["kind"] == "const" and rhs["value"] == 3


def test_callsite_add_dig_truthful_sat_through_real_solver(tmp_path: Path) -> None:
    result = run_source_through_real_solver(tmp_path / "cs-add-truth", _TRUTHFUL)
    assert result.verdict == "sat", (
        result.verdict,
        [row.get("status") for row in result.prove_doc.get("rows", [])],
        [row.get("reason") for row in result.prove_doc.get("rows", [])],
    )
    assert result.proofir_emitted


def test_callsite_add_dig_dual_ir_has_contradictory_rhs() -> None:
    """Dual-assert material: shared `#euf#` key, RHS 3 vs 4 (injectivity fuel)."""
    payload = lift_file_payload(_DUAL, "t.py")
    asserts = [
        r
        for r in payload.ir
        if r.name.startswith("A#euf#") and r.name.endswith("::assertion")
    ]
    assert len(asserts) == 2
    # Same callsite key so ambient / mint conjoin can form the dual.
    assert {r.name for r in asserts} == {asserts[0].name}
    rhs = sorted(r.inv.ir_formula.args[1].value for r in asserts)
    assert rhs == [3, 4]
    # Shared left coordinate (call:A).
    lefts = {r.inv.ir_formula.args[0].name for r in asserts}
    assert lefts == {"call:A"}


def test_callsite_add_dig_lying_unsat_through_real_solver(tmp_path: Path) -> None:
    """Lying twin A()==4 with ground post out=3 → unsat (prove path)."""
    result = run_source_through_real_solver(tmp_path / "cs-add-lie", _LYING)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_callsite_add_dig_dual_structural_unsat(tmp_path: Path) -> None:
    """Dual py.eq(call:A(),3) ∧ py.eq(call:A(),4) → structural unsat pre-SMT."""
    result = run_source_through_real_solver(tmp_path / "cs-add-dual", _DUAL)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    reasons = " ".join(
        str(row.get("reason") or "") for row in result.prove_doc.get("rows", [])
    )
    assert result.verdict == "unsat", (result.verdict, statuses, reasons)
    assert "structural" in reasons
    assert "equals both" in reasons
    assert "refused" not in statuses
