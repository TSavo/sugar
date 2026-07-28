"""Imported Name/Attribute VALUE occurrences get final-checked receipts.

Call targets already mint via ``authenticated_import_use_receipts``. Value
loads (caller actuals, helper identity operands) need the same exact-coordinate
authority without spelling. Twins pin: move changes the receipt; non-imported
name mints none; tampered CID refuses; Call-target surface stays unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.import_binding import (
    authenticated_import_use_receipts,
    authenticated_import_value_use_receipts,
)
from sugar_lift_python_source.source_oracle import path_source


def _write(path: Path, text: str) -> tuple[str, str]:
    path.write_text(text, encoding="utf-8")
    source, _, source_cid = path_source(str(path))
    return source, source_cid


def test_value_use_receipt_changes_when_source_moves(tmp_path: Path) -> None:
    """Moving an imported Name value use changes the receipt useSite/CID."""
    early = tmp_path / "early.py"
    late = tmp_path / "late.py"
    early_src, early_cid = _write(early, "from pkg import f\nx = f\n")
    late_src, late_cid = _write(late, "from pkg import f\n\nx = f\n")

    early_receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, early, early_src, early_cid, module_identities={}
    )
    late_receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, late, late_src, late_cid, module_identities={}
    )

    early_f = [r for r in early_receipts if r.target_symbol == "python:pkg.f"]
    late_f = [r for r in late_receipts if r.target_symbol == "python:pkg.f"]
    assert len(early_f) == 1
    assert len(late_f) == 1
    assert early_f[0].use["useSite"] != late_f[0].use["useSite"]
    assert early_f[0].use["cid"] != late_f[0].use["cid"]
    assert early_f[0].use["useSite"]["startLine"] != late_f[0].use["useSite"]["startLine"]


def test_non_imported_name_gets_no_value_use_receipt(tmp_path: Path) -> None:
    path = tmp_path / "local.py"
    source, source_cid = _write(
        path,
        "def f():\n    return 1\n\nx = f\n",
    )
    receipts, outcomes = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    assert receipts == []
    assert outcomes == {}


def test_tampered_source_cid_refuses_value_use_receipts(tmp_path: Path) -> None:
    path = tmp_path / "consumer.py"
    source, honest_cid = _write(path, "from pkg import f\nx = f\n")
    lying = "blake3-512:" + "0" * 128
    assert lying != honest_cid
    with pytest.raises(ValueError, match="authenticated import-use source CID is stale"):
        authenticated_import_value_use_receipts(
            tmp_path, path, source, lying, module_identities={}
        )


def test_call_target_receipts_unchanged_when_value_uses_exist(tmp_path: Path) -> None:
    """Value-use enrollment must not alter Call-target receipts or outcomes."""
    path = tmp_path / "mixed.py"
    # Name value load, Attribute value load, and Call targets share one module.
    source, source_cid = _write(
        path,
        "import pkg as tm\n"
        "from pkg import f\n"
        "x = f\n"
        "y = tm.box_expected\n"
        "f(1)\n"
        "tm.box_expected((1,), tm.array)\n",
    )
    call_receipts, call_outcomes = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    value_receipts, value_outcomes = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )

    assert call_receipts, "Call targets must still mint"
    assert all(r.demand["kind"] == "call-contract-demand" for r in call_receipts)
    assert set(call_outcomes.values()) == {"authenticated-import-use"}

    assert value_receipts, "value loads must mint"
    assert all(r.demand["kind"] == "import-value-use-demand" for r in value_receipts)
    assert set(value_outcomes.values()) == {"authenticated-import-value-use"}

    # Call sites and value sites are disjoint coordinates.
    call_sites = {
        (
            r.use["useSite"]["startLine"],
            r.use["useSite"]["startCol"],
            r.use["useSite"]["endLine"],
            r.use["useSite"]["endCol"],
        )
        for r in call_receipts
    }
    value_sites = {
        (
            r.use["useSite"]["startLine"],
            r.use["useSite"]["startCol"],
            r.use["useSite"]["endLine"],
            r.use["useSite"]["endCol"],
        )
        for r in value_receipts
    }
    assert call_sites.isdisjoint(value_sites)

    # Attribute actual ``tm.array`` and Name load ``f`` appear as value uses.
    targets = {r.target_symbol for r in value_receipts}
    assert "python:pkg.f" in targets
    assert "python:pkg.box_expected" in targets
    assert "python:pkg.array" in targets

    # Call-target symbols still include the call heads only.
    call_targets = {r.target_symbol for r in call_receipts}
    assert "python:pkg.f" in call_targets
    assert "python:pkg.box_expected" in call_targets

    for receipt in (*call_receipts, *value_receipts):
        receipt.revalidate()


def test_attribute_value_use_pins_exact_coordinate(tmp_path: Path) -> None:
    path = tmp_path / "attr.py"
    source, source_cid = _write(
        path,
        "import unprivileged as tm\nactual = tm.box_expected\n",
    )
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    attr = [r for r in receipts if r.target_symbol == "python:unprivileged.box_expected"]
    assert len(attr) == 1
    site = attr[0].use["useSite"]
    # ``tm.box_expected`` on line 2 — exact Attribute span, not the whole assign.
    assert site["startLine"] == 2
    assert site["endLine"] == 2
    assert site["endCol"] > site["startCol"]
    assert attr[0].use["cid"].startswith("blake3-512:")
    attr[0].revalidate()
