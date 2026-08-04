"""Unit twin: foreign site-packages trap for checkout import roots + authenticate_lift.

#6997 landed the S0 fix and CI-shaped subprocess teeth. This file adds only
what that suite still lacks as a *unit-level* reproduction of the failure mode:

1. ``activate_checkout_import_roots`` puts the checkout root FIRST when a real
   site-packages path is *already* on ``sys.path`` (not a placeholder string).
2. A module whose ``__file__`` is a *planted* foreign site-packages copy FAILS
   ``authenticate_lift`` (regression tooth: can fail even when CI is green).

#6997 already covers (do not re-land): action/tool wiring, truthful CI shape
without first-party in site-packages, activate-after-import subprocess lie,
PYTHONPATH-wins-when-both-exist subprocess. See
``tests/test_ci_python_env_checkout_lift_import.py``.
"""

from __future__ import annotations

from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType

import pytest

from repo_root_test_support import resolve_repo_root

from sugar_lift_py_tests.authenticated_pytest import (
    ExecutionEnvironmentMismatch,
    activate_checkout_import_roots,
    authenticate_lift,
)


def test_activate_checkout_import_roots_puts_checkout_first_when_site_packages_already_on_path(
    tmp_path: Path,
) -> None:
    """Trap present on path; activation must still prefix the checkout root."""
    repo, checkout_src, purelib = _mini_repo_with_planted_site_packages(tmp_path)
    search_path = [str(purelib), "ambient-tail"]

    activate_checkout_import_roots(repo, search_path)

    checkout = str(checkout_src.resolve())
    site = str(purelib)
    assert checkout in search_path
    assert site in search_path
    # All managed checkout roots are prefixed; site-packages must stay after them.
    assert search_path.index(checkout) < search_path.index(site)
    assert search_path.index(site) < search_path.index("ambient-tail")


def test_authenticate_lift_refuses_module_whose_file_is_planted_site_packages_copy(
    tmp_path: Path,
) -> None:
    """Lying twin: planted site-packages __file__ fails authenticate_lift."""
    repo, checkout_src, purelib = _mini_repo_with_planted_site_packages(tmp_path)
    foreign_init = purelib / "sugar_lift_py_tests" / "__init__.py"
    assert foreign_init.is_file()

    foreign = ModuleType("sugar_lift_py_tests")
    foreign.__file__ = str(foreign_init.resolve())
    foreign.__spec__ = ModuleSpec(
        "sugar_lift_py_tests",
        loader=None,
        origin=str(foreign_init.resolve()),
    )

    with pytest.raises(
        ExecutionEnvironmentMismatch,
        match="lift import escaped the synced checkout",
    ):
        authenticate_lift(foreign, repo)

    # Truthful face of the same plant: checkout-resident path is accepted.
    truthful_init = checkout_src / "sugar_lift_py_tests" / "__init__.py"
    truthful = ModuleType("sugar_lift_py_tests")
    truthful.__file__ = str(truthful_init.resolve())
    truthful.__spec__ = ModuleSpec(
        "sugar_lift_py_tests",
        loader=None,
        origin=str(truthful_init.resolve()),
    )
    identity = authenticate_lift(truthful, repo)
    assert identity.loaded_from.is_relative_to(checkout_src.resolve())


def _mini_repo_with_planted_site_packages(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    """Checkout + foreign site-packages copy of sugar_lift_py_tests (the S0 trap)."""
    repo = tmp_path / "sugar"
    checkout_src = repo / "implementations/python/sugar-lift-py-tests/src"
    checkout_pkg = checkout_src / "sugar_lift_py_tests"
    checkout_pkg.mkdir(parents=True)
    (checkout_pkg / "__init__.py").write_text(
        "MARK = 'checkout'\n", encoding="utf-8"
    )

    # Sibling roots required by production Dockerfile PYTHONPATH declaration.
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

    # Prefer production managed tool when present (shared with #6997 action).
    prod_tool = resolve_repo_root() / "tools" / "managed_checkout_pythonpath.py"
    tool_dst = repo / "tools" / "managed_checkout_pythonpath.py"
    tool_dst.parent.mkdir(parents=True, exist_ok=True)
    if prod_tool.is_file():
        tool_dst.write_text(prod_tool.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        tool_dst.write_text(
            "from pathlib import Path\n"
            "def managed_checkout_import_roots(repo_root):\n"
            "    root = Path(repo_root).resolve()\n"
            "    return [root / 'implementations/python/sugar-lift-py-tests/src']\n",
            encoding="utf-8",
        )

    dockerfile = repo / "tools/sugar-build/Dockerfile"
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

    purelib = tmp_path / "venv/lib/python3.12/site-packages"
    foreign_pkg = purelib / "sugar_lift_py_tests"
    foreign_pkg.mkdir(parents=True)
    (foreign_pkg / "__init__.py").write_text(
        "MARK = 'site-packages'\n", encoding="utf-8"
    )
    return repo, checkout_src, purelib
