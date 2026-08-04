#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


import sys

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from sugar_repo_root import resolve_repo_root

def _repo_root() -> Path:
    return resolve_repo_root()


def main() -> int:
    root = _repo_root()
    python_root = root / "implementations/python"
    for package in ("sugar-lift-python-source", "sugar-lift-py-tests"):
        sys.path.insert(0, str(python_root / package / "src"))

    from sugar_lift_py_tests.idd.pandas_wall import main as pandas_wall_main

    return pandas_wall_main(["--root", str(root), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
