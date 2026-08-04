from __future__ import annotations

import subprocess
from pathlib import Path

from sugar_lift_py_tests.source_provenance import (
    loaded_python_source_identity,
    source_provenance_for_roots,
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, text=True, capture_output=True
    )
    return result.stdout.strip()


def test_git_source_provenance_reports_commit_and_dirty(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "a.py").write_text("A = 1\n")
    (second / "b.py").write_text("B = 2\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "fixture")
    head = _git(tmp_path, "rev-parse", "HEAD")

    assert source_provenance_for_roots([first, second]) == {
        "identity": head,
        "kind": "git",
        "dirty": False,
    }

    (second / "b.py").write_text("B = 3\n")
    assert source_provenance_for_roots([first, second]) == {
        "identity": head,
        "kind": "git",
        "dirty": True,
    }


def test_non_git_source_provenance_is_content_addressed(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "a.py").write_text("A = 1\n")
    (second / "b.py").write_text("B = 2\n")

    provenance = source_provenance_for_roots([first, second])
    assert provenance["kind"] == "content"
    assert provenance["dirty"] is False
    assert str(provenance["identity"]).startswith("blake3-512:")
    assert len(str(provenance["identity"])) == len("blake3-512:") + 128


def _python_package_tree(root: Path, package: str, marker: str) -> Path:
    package_root = root / "src" / package
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text(f"MARKER = {marker!r}\n")
    return package_root


def test_loaded_python_source_identity_carries_actual_origins_and_content_cids(
    tmp_path: Path,
) -> None:
    declared = tmp_path / "declared"
    loaded = tmp_path / "loaded"
    package_names = (
        "sugar_lift_py_tests",
        "sugar_lift_python_source",
        "sugar_source_tree",
    )
    declared_roots = {
        name: _python_package_tree(declared / name, name, "same")
        for name in package_names
    }
    loaded_roots = {
        name: _python_package_tree(loaded / name, name, "same")
        for name in package_names
    }

    identity = loaded_python_source_identity(
        declared_package_roots=declared_roots,
        loaded_package_origins={
            name: root / "__init__.py" for name, root in loaded_roots.items()
        },
    )

    assert identity["schema"] == "loaded-source-identity/v1"
    assert [row["subject"] for row in identity["declared"]] == list(package_names)
    assert [row["subject"] for row in identity["loaded"]] == list(package_names)
    for declared_row, loaded_row in zip(
        identity["declared"], identity["loaded"], strict=True
    ):
        assert declared_row["contentCid"] == loaded_row["contentCid"]
        assert declared_row["origin"] != loaded_row["origin"]
        assert str(loaded_row["origin"]).endswith("/__init__.py")


def test_loaded_python_source_identity_exposes_stale_content_without_forging_status(
    tmp_path: Path,
) -> None:
    declared_root = _python_package_tree(
        tmp_path / "declared", "sugar_lift_py_tests", "current"
    )
    stale_root = _python_package_tree(
        tmp_path / "stale", "sugar_lift_py_tests", "historical"
    )

    identity = loaded_python_source_identity(
        declared_package_roots={"sugar_lift_py_tests": declared_root},
        loaded_package_origins={"sugar_lift_py_tests": stale_root / "__init__.py"},
    )

    assert identity["declared"][0]["contentCid"] != identity["loaded"][0]["contentCid"]
    assert "matched" not in identity
