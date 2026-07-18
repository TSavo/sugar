from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import SourceFragment, default_catalog
from sugar_lift_py_tests.sugar.package_source_accounting_sugar import (
    PackageSourceAccountingSugar,
    package_source_audits_for_source,
    source_ledger_for_source_audits,
)


def test_package_source_accounting_is_a_registered_module_recognizer() -> None:
    site = SourceFragment.from_source("import os\n", "example.py")
    candidates = default_catalog().candidates_for(SugarRole.PACKAGE_SOURCE, site)

    assert [candidate.name for candidate in candidates] == [
        "PackageSourceAccountingSugar"
    ]
    assert PackageSourceAccountingSugar.owns(site)


def test_package_source_accounting_bad_twin_without_import_has_no_audit(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    audits = package_source_audits_for_source(
        filename="test_no_package.py",
        source="def test_no_package():\n    assert 1 == 1\n",
    )

    assert [
        audit for audit in audits if audit.get("role") == "python.package-source"
    ] == []


def test_package_source_accounting_emits_structural_package_audit(
    tmp_path: Path, monkeypatch
) -> None:
    package = tmp_path / "vendorpkg"
    package.mkdir()
    (package / "__init__.py").write_text("from .core import f\n", encoding="utf-8")
    (package / "core.py").write_text(
        (
            "VALUE = 1\n"
            "\n"
            "class Box:\n"
            "    pass\n"
            "\n"
            "def f(value):\n"
            "    tmp = value + VALUE\n"
            "    return int(tmp)\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "structural")
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_LOCI", "summary")
    monkeypatch.setenv("SUGAR_PY_PACKAGE_ACCOUNTING_SAMPLE_LIMIT", "2")

    source_audits = package_source_audits_for_source(
        filename="test_vendorpkg.py",
        source=(
            "from vendorpkg.core import f\n"
            "\n"
            "def test_vendor_call():\n"
            "    assert f(1) == 2\n"
        ),
    )

    package_audits = [
        audit
        for audit in source_audits
        if audit.get("role") == "python.package-source"
        and audit.get("package") == "vendorpkg"
    ]
    assert len(package_audits) == 1
    audit = package_audits[0]
    assert audit["accounting_mode"] == "structural"
    assert audit["loci_elided"] is True
    assert "loci" not in audit
    assert audit["package_file_count"] == 2
    assert audit["totals"]["source_loci"] > 0
    assert audit["totals"]["unclassified_source"] > 0
    assert audit["ast_type_counts"]["unclassified"]["Name"] > 0
    assert audit["ast_type_counts"]["unclassified"]["Call"] > 0
    assert audit["ast_type_counts"]["unclassified"]["Assign"] > 0
    ledger = source_ledger_for_source_audits(source_audits)
    assert ledger["source_loci"] >= audit["totals"]["source_loci"]


def test_package_source_accounting_is_opt_in(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "vendorpkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", raising=False)

    source_audits = package_source_audits_for_source(
        filename="test_vendorpkg.py",
        source=(
            "import vendorpkg\n"
            "\n"
            "def test_vendor_call():\n"
            "    assert vendorpkg is vendorpkg\n"
        ),
    )

    assert [
        audit for audit in source_audits if audit.get("role") == "python.package-source"
    ] == []
