from __future__ import annotations

import subprocess
from pathlib import Path

from sugar_lift_py_tests.source_provenance import source_provenance_for_roots


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
