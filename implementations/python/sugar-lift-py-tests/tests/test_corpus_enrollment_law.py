"""Teeth for corpus_enrollment_law — criterion 1 denominator / enrollment.

Discrimination only: planted trees and predicate source. Does not lift the
pandas corpus (report-first; no lease).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "corpus_enrollment_law.py"
_SPEC = importlib.util.spec_from_file_location("corpus_enrollment_law", _SCANNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def _write(root: Path, rel: str, text: str = "x = 1\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_membership_predicate_has_no_manager_or_call_filter() -> None:
    """The predicate source must not smuggle vendor/call filters."""
    source = _SCANNER.membership_predicate_source()
    hits = _SCANNER.predicate_has_vendor_or_call_filter(source)
    assert hits == [], f"membership predicate smuggles {hits}"


def test_denominator_is_sourcetree_paths_not_a_target_count(tmp_path: Path) -> None:
    """Whatever SourceTree.paths yields IS the count — never a hard-coded N."""
    root = tmp_path / "pandas"
    _write(root, "a.py")
    _write(root, "pkg/b.py")
    _write(root, "pkg/__pycache__/c.py")  # must not enroll via discovery
    # non-py ignored
    (root / "readme.txt").write_text("nope\n", encoding="utf-8")

    paths = _SCANNER.denominator_paths(root)
    rels = sorted(p.relative_to(root).as_posix() for p in paths)
    assert rels == ["a.py", "pkg/b.py"]
    assert len(paths) == 2  # derived, not targeted a priori


def test_is_corpus_py_path_rejects_non_py_and_pycache(tmp_path: Path) -> None:
    root = tmp_path / "c"
    py = _write(root, "ok.py")
    bad = root / "x.txt"
    bad.write_text("x\n", encoding="utf-8")
    pyc = _write(root, "__pycache__/z.py")
    assert _SCANNER.is_corpus_py_path(py, root=root)
    assert not _SCANNER.is_corpus_py_path(bad, root=root)
    assert not _SCANNER.is_corpus_py_path(pyc, root=root)


def test_enrollment_from_recensus_missing_terminals(tmp_path: Path) -> None:
    """Unenrolled = denominator − terminal identities from a live receipt shape."""
    root = tmp_path / "pandas"
    a = _write(root, "a.py")
    b = _write(root, "b.py")
    _write(root, "c.py")
    # Fabricate receipt: only a and b got terminals
    payload = {
        "denominator": {
            "enrolledFiles": [
                _SCANNER.relative_file_identity(a, corpus_root=root),
                _SCANNER.relative_file_identity(b, corpus_root=root),
                _SCANNER.relative_file_identity(root / "c.py", corpus_root=root),
            ],
            "missingFiles": [
                _SCANNER.relative_file_identity(root / "c.py", corpus_root=root),
            ],
        }
    }
    report = _SCANNER.measure_enrollment(
        corpus_root=root, recensus_payload=payload
    )
    assert report.measured_enrollment is True
    assert report.denominator_files == 3
    assert report.enrolled_files == 2
    assert report.unenrolled_files == 1
    assert report.unenrolled_identities == (
        _SCANNER.relative_file_identity(root / "c.py", corpus_root=root),
    )


def test_without_receipt_enrollment_is_unmeasured(tmp_path: Path) -> None:
    root = tmp_path / "pandas"
    _write(root, "only.py")
    report = _SCANNER.measure_enrollment(corpus_root=root, recensus_payload=None)
    assert report.denominator_files == 1
    assert report.measured_enrollment is False
    assert report.unenrolled_files is None
    assert "UNMEASURED" in report.note


def test_cli_exits_2_when_enrollment_unmeasured(tmp_path: Path) -> None:
    root = tmp_path / "pandas"
    _write(root, "only.py")
    code = _SCANNER.main(["--corpus-root", str(root)])
    assert code == 2


def test_cli_exits_1_when_unenrolled_nonzero(tmp_path: Path) -> None:
    root = tmp_path / "pandas"
    a = _write(root, "a.py")
    _write(root, "b.py")
    receipt = tmp_path / "recensus.json"
    receipt.write_text(
        json.dumps(
            {
                "denominator": {
                    "enrolledFiles": [
                        _SCANNER.relative_file_identity(a, corpus_root=root),
                        _SCANNER.relative_file_identity(root / "b.py", corpus_root=root),
                    ],
                    "missingFiles": [
                        _SCANNER.relative_file_identity(root / "b.py", corpus_root=root),
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    code = _SCANNER.main(
        ["--corpus-root", str(root), "--from-recensus", str(receipt)]
    )
    assert code == 1
