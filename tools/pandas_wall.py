#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    root = _repo_root()
    src = root / "implementations/python/sugar-lift-py-tests/src"
    sys.path.insert(0, str(src))

    from sugar_lift_py_tests.idd.pandas_wall import main as pandas_wall_main

    return pandas_wall_main(["--root", str(root), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
