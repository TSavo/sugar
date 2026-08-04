# SPDX-License-Identifier: MIT OR Apache-2.0
"""Repo tests must resolve the checkout without importing the test kit.

The test kit is not installed at every repo-test entrance: pre-dispatch jobs,
plain-root collection, and direct checkout scripts all run earlier.  Those
callers use the package-free ``tools/sugar_repo_root.py`` twin (seated through
``repo_root_test_support``), while package-owned tests keep their package door.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from repo_root_test_support import resolve_repo_root

from repo_test_package_root_import_census import forbidden_import_lines, scan


def test_wrong_door_detector_distinguishes_package_from_tools_twin(
    tmp_path: Path,
) -> None:
    package_door = tmp_path / "package_door.py"
    package_door.write_text(
        "from sugar_lift_py_tests.repo_root import resolve_repo_root\n",
        encoding="utf-8",
    )
    tools_twin = tmp_path / "tools_twin.py"
    tools_twin.write_text(
        "from sugar_repo_root import resolve_repo_root\n", encoding="utf-8"
    )

    assert forbidden_import_lines(package_door) == (1,)
    assert forbidden_import_lines(tools_twin) == ()


def test_repo_level_tests_never_import_the_package_root_door() -> None:
    tests_root = resolve_repo_root() / "tests"
    offenders = {
        str(path.relative_to(tests_root)): lines for path, lines in scan(tests_root)
    }

    assert offenders == {}, (
        "repo-level tests run before sugar_lift_py_tests is guaranteed installed; "
        "route them through the package-free tools/sugar_repo_root.py twin: "
        f"{offenders}"
    )


def test_path_integrity_workflow_enforces_both_root_axes() -> None:
    workflow = (
        resolve_repo_root() / ".github/workflows/recensus-path-smoke.yml"
    ).read_text(encoding="utf-8")

    assert "python3 tools/repo_root_parents_n_census.py" in workflow
    assert "python3 tools/repo_test_package_root_import_census.py" in workflow


def test_lpt_shard_test_collects_when_test_kit_package_is_unavailable() -> None:
    """The observed pre-install failure is impossible through the tools twin."""
    tests_root = Path(__file__).resolve().parent
    code = """
import importlib.abc
import sys

class RejectTestKit(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "sugar_lift_py_tests" or fullname.startswith("sugar_lift_py_tests."):
            raise ModuleNotFoundError("test kit deliberately unavailable")
        return None

sys.meta_path.insert(0, RejectTestKit())
import test_lpt_file_shards
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tests_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
