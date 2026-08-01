"""CI environment: first-party lift resolves from checkout, not site-packages.

The defect that killed S0.1/S0.2: python-test-environment wheel-installed
first-party sugar-lift-* into the venv, so ``import sugar_lift_py_tests``
bound site-packages before checkout roots could win. authenticate_lift
correctly refused (do not weaken it).

These twins exercise the *environment contract*, not a bare-dev checkout
path alone: a foreign site-packages copy is always present as the lying
trap. Truthful setup is checkout PYTHONPATH first (action's post-install
export). Lying setup is site-packages first / no checkout roots.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.authenticated_pytest import (
    ExecutionEnvironmentMismatch,
    activate_checkout_import_roots,
    authenticate_lift,
)


REPO = Path(__file__).resolve().parents[1]


def test_third_party_requirements_exclude_first_party_packages() -> None:
    """Authority [test] deps install without sugar-lift first-party names."""
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools/python_test_third_party_requirements.py"),
            "--repo-root",
            str(REPO),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    assert lines, "third-party list must be non-empty"
    joined = "\n".join(lines).lower()
    for banned in (
        "sugar-lift-py-tests",
        "sugar-lift-python-source",
        "sugar-source-tree",
    ):
        assert banned not in joined, f"first-party leaked into third-party list: {banned}"
    assert any(line.startswith("pandas==") for line in lines)
    assert any(line.startswith("numpy==") for line in lines)


def test_checkout_pythonpath_is_declared_managed_closure_under_repo() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools/python_test_checkout_pythonpath.py"),
            "--repo-root",
            str(REPO),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    path = completed.stdout.strip()
    assert path
    for entry in path.split(":"):
        resolved = Path(entry).resolve()
        assert resolved.is_dir(), entry
        assert resolved.is_relative_to(REPO.resolve()), entry
    assert "sugar-lift-py-tests/src" in path.replace("\\", "/")


def test_truthful_ci_shaped_import_loads_lift_from_checkout(tmp_path: Path) -> None:
    """Truthful: checkout root first → sugar_lift_py_tests.__file__ under checkout.

    Foreign site-packages copy is present (the machine trap that failed S0).
    """
    repo, checkout_init, site_init = _mini_repo_with_foreign_site_packages(tmp_path)
    path: list[str] = [str(site_init.parent.parent)]  # site-packages on path
    activate_checkout_import_roots(repo, path)
    assert path[0] == str(
        (repo / "implementations/python/sugar-lift-py-tests/src").resolve()
    )

    code = (
        "import importlib, sys\n"
        f"sys.path[:0] = {path!r}\n"
        "mod = importlib.import_module('sugar_lift_py_tests')\n"
        "print(mod.MARK)\n"
        "print(mod.__file__)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=False,
        cwd=str(repo),
    )
    assert completed.returncode == 0, completed.stderr
    mark, loaded = completed.stdout.strip().splitlines()
    assert mark == "checkout"
    assert Path(loaded).resolve().is_relative_to(
        (repo / "implementations/python/sugar-lift-py-tests/src").resolve()
    )
    # Authority tooth: authenticate_lift accepts this load.
    from types import ModuleType
    from importlib.machinery import ModuleSpec

    module = ModuleType("sugar_lift_py_tests")
    module.__file__ = loaded
    module.__spec__ = ModuleSpec("sugar_lift_py_tests", loader=None, origin=loaded)
    assert authenticate_lift(module, repo).loaded_from.is_relative_to(
        (repo / "implementations/python/sugar-lift-py-tests/src").resolve()
    )


def test_lying_site_packages_first_party_is_refused_by_authenticate_lift(
    tmp_path: Path,
) -> None:
    """Lying twin: first-party from site-packages fails authenticate_lift."""
    repo, _checkout_init, site_init = _mini_repo_with_foreign_site_packages(tmp_path)
    from types import ModuleType
    from importlib.machinery import ModuleSpec

    foreign = ModuleType("sugar_lift_py_tests")
    foreign.__file__ = str(site_init)
    foreign.__spec__ = ModuleSpec(
        "sugar_lift_py_tests", loader=None, origin=str(site_init)
    )
    with pytest.raises(
        ExecutionEnvironmentMismatch, match="lift import escaped the synced checkout"
    ):
        authenticate_lift(foreign, repo)


def test_lying_import_without_checkout_roots_binds_site_packages(
    tmp_path: Path,
) -> None:
    """Without checkout PYTHONPATH, import binds the foreign site-packages copy.

    That is the S0 failure mode. The environment must not do this.
    """
    _repo, _checkout_init, site_init = _mini_repo_with_foreign_site_packages(tmp_path)
    site_packages = str(site_init.parent.parent)
    code = (
        "import importlib, sys\n"
        f"sys.path.insert(0, {site_packages!r})\n"
        "mod = importlib.import_module('sugar_lift_py_tests')\n"
        "print(mod.MARK)\n"
        "print(mod.__file__)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    mark, loaded = completed.stdout.strip().splitlines()
    assert mark == "site-packages"
    assert "site-packages" in loaded.replace("\\", "/")


def _mini_repo_with_foreign_site_packages(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    repo = tmp_path / "sugar"
    checkout_pkg = (
        repo / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests"
    )
    checkout_pkg.mkdir(parents=True)
    checkout_init = checkout_pkg / "__init__.py"
    checkout_init.write_text("MARK = 'checkout'\n", encoding="utf-8")
    # Sibling roots required by Dockerfile PYTHONPATH declaration.
    for rel in (
        "implementations/python/libsugar-py",
        "implementations/python/sugar-build-witness/src",
        "implementations/python/sugar-emit-python-hypothesis/src",
        "implementations/python/sugar-emit-python-pytest/src",
        "implementations/python/sugar-emit-python-unittest/src",
        "implementations/python/sugar-lift-py-pytest-witness/src",
        "implementations/python/sugar-lift-python-source/src",
        "implementations/python/sugar-source-tree/src",
    ):
        (repo / rel).mkdir(parents=True, exist_ok=True)
    dockerfile = repo / "tools/sugar-build/Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text(
        "ENV PYTHONPATH="
        "/workspace/sugar/implementations/python/libsugar-py:"
        "/workspace/sugar/implementations/python/sugar-build-witness/src:"
        "/workspace/sugar/implementations/python/sugar-emit-python-hypothesis/src:"
        "/workspace/sugar/implementations/python/sugar-emit-python-pytest/src:"
        "/workspace/sugar/implementations/python/sugar-emit-python-unittest/src:"
        "/workspace/sugar/implementations/python/sugar-lift-py-pytest-witness/src:"
        "/workspace/sugar/implementations/python/sugar-lift-py-tests/src:"
        "/workspace/sugar/implementations/python/sugar-lift-python-source/src:"
        "/workspace/sugar/implementations/python/sugar-source-tree/src\n",
        encoding="utf-8",
    )
    site_pkg = tmp_path / "venv/lib/python3.12/site-packages/sugar_lift_py_tests"
    site_pkg.mkdir(parents=True)
    site_init = site_pkg / "__init__.py"
    site_init.write_text("MARK = 'site-packages'\n", encoding="utf-8")
    return repo, checkout_init, site_init
