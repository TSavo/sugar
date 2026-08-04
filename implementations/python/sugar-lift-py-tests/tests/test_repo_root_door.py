# SPDX-License-Identifier: MIT OR Apache-2.0
"""Repo-root resolve door: ask for sugar-build.toml, never count parents[N].

THE defect that blocked floors: installed into site-packages, parents[5]
resolved to the python-test-environment temp dir (a real path that does not
contain sugar-build.toml). Authentication then FileNotFoundError-ed far away
as if the corpus authority failed.

Teeth:
- Truthful: from a checkout cwd, resolve finds sugar-build.toml.
- Site-packages twin: process "lives" under a venv layout; env/cwd still resolve.
- Lying twin: missing sugar-build.toml refuses LOUDLY naming the marker
  (not a FileNotFoundError on a wrong path).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from sugar_lift_py_tests.repo_root import (
    MARKER,
    RepoRootUnresolved,
    resolve_repo_root,
    sugar_lift_py_tests_package_root,
)

def _write_marker(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    marker = repo / MARKER
    marker.write_text(
        textwrap.dedent("""\
            [tools]
            python = "3.12.13"
            """),
        encoding="utf-8",
    )
    return marker


def test_resolves_by_walking_from_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "checkout"
    _write_marker(repo)
    nested = repo / "implementations" / "python" / "sugar-lift-py-tests"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.delenv("SUGAR_REPO_ROOT", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    assert resolve_repo_root() == repo.resolve()


def test_site_packages_layout_resolves_via_github_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE CI twin: package under site-packages, checkout only via GITHUB_WORKSPACE.

    Simulates the floors job layout: __file__ would live under
    sugar-python-test-environment/venv/.../site-packages, while the real
    sugar-build.toml is under the Actions workspace.
    """
    checkout = tmp_path / "actions-workspace" / "sugar"
    _write_marker(checkout)
    # Fake venv site-packages tree (no sugar-build.toml here — the old defect).
    site_pkg = (
        tmp_path
        / "sugar-python-test-environment"
        / "venv"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "sugar_lift_py_tests"
    )
    site_pkg.mkdir(parents=True)
    (site_pkg / "authenticated_pytest.py").write_text(
        "# fake install\n", encoding="utf-8"
    )
    # Cwd is the temp env (wrong for parents[N]); env names the checkout.
    monkeypatch.chdir(tmp_path / "sugar-python-test-environment")
    monkeypatch.delenv("SUGAR_REPO_ROOT", raising=False)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(checkout))
    assert resolve_repo_root() == checkout.resolve()


def test_site_packages_layout_resolves_via_sugar_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "repo"
    _write_marker(checkout)
    monkeypatch.chdir(tmp_path)  # no marker in cwd
    monkeypatch.setenv("SUGAR_REPO_ROOT", str(checkout))
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    assert resolve_repo_root() == checkout.resolve()


def test_missing_marker_refuses_naming_sugar_build_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lying twin: undischarged root must panic with the marker name, not a wrong path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUGAR_REPO_ROOT", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    with pytest.raises(RepoRootUnresolved) as raised:
        resolve_repo_root(start=tmp_path)
    message = str(raised.value)
    assert MARKER in message
    assert "looked for" in message or "searched" in message
    # Must not pretend a wrong directory is the root.
    assert "FileNotFoundError" not in message


def test_env_pointing_at_directory_without_marker_is_not_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plausible path that lacks sugar-build.toml is not a silent root."""
    decoy = tmp_path / "almost"
    decoy.mkdir()
    real = tmp_path / "real"
    _write_marker(real)
    monkeypatch.setenv("SUGAR_REPO_ROOT", str(decoy))
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.chdir(real)
    # decoy env is skipped; walk from cwd finds real
    assert resolve_repo_root() == real.resolve()


def test_package_root_is_under_resolved_monorepo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "sugar"
    _write_marker(repo)
    package = repo / "implementations" / "python" / "sugar-lift-py-tests"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        '[project]\nname = "sugar-lift-py-tests"\n', encoding="utf-8"
    )
    monkeypatch.setenv("SUGAR_REPO_ROOT", str(repo))
    monkeypatch.chdir(tmp_path)
    assert sugar_lift_py_tests_package_root() == package.resolve()


def test_declared_interpreter_runtime_uses_door_not_parents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blocking site: declared_interpreter_runtime reads sugar-build via the door."""
    repo = tmp_path / "sugar"
    _write_marker(repo)
    # Authority version must match what declared_interpreter_runtime reads.
    (repo / MARKER).write_text(
        '[tools]\npython = "3.12.13"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SUGAR_REPO_ROOT", str(repo))
    monkeypatch.chdir(tmp_path)
    from sugar_lift_py_tests.authenticated_pytest import declared_interpreter_runtime

    assert declared_interpreter_runtime() == "cpython-3.12.13"


def test_idd_wall_mains_do_not_count_parents_for_repo_root() -> None:
    """Residual parents[5] seats routed: wall CLIs use the resolve door."""
    import inspect

    from sugar_lift_py_tests.idd import numpy_wall, pandas_wall

    for mod in (numpy_wall, pandas_wall):
        src = inspect.getsource(mod.main)
        assert "parents[5]" not in src, mod.__name__
        assert "resolve_repo_root" in src, mod.__name__
