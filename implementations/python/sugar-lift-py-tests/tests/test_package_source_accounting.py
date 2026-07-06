from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.lib import lift_source


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

    report = lift_source(
        "test_vendorpkg.py",
        (
            "from vendorpkg.core import f\n"
            "\n"
            "def test_vendor_call():\n"
            "    assert f(1) == 2\n"
        ),
        memento_file="test_vendorpkg.py",
    ).payload.to_rpc()

    package_audits = [
        audit
        for audit in report["sourceAudits"]
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
    assert report["sourceLedger"]["source_loci"] >= audit["totals"]["source_loci"]


def test_package_source_accounting_is_opt_in(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "vendorpkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delenv("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", raising=False)

    report = lift_source(
        "test_vendorpkg.py",
        (
            "import vendorpkg\n"
            "\n"
            "def test_vendor_call():\n"
            "    assert vendorpkg is vendorpkg\n"
        ),
        memento_file="test_vendorpkg.py",
    ).payload.to_rpc()

    assert [
        audit
        for audit in report["sourceAudits"]
        if audit.get("role") == "python.package-source"
    ] == []
