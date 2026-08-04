# SPDX-License-Identifier: MIT OR Apache-2.0
"""Package-free entrance to the tools-owned monorepo root resolver.

Repo-level tests are collected before the Python test kit is necessarily
installed.  Seat the package-independent ``tools/sugar_repo_root.py`` twin
once for that population; never import ``sugar_lift_py_tests.repo_root`` here.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(_TOOLS))

from sugar_repo_root import RepoRootUnresolved, resolve_repo_root  # noqa: E402

__all__ = ("RepoRootUnresolved", "resolve_repo_root")
