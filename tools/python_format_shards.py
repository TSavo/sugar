#!/usr/bin/env python3
"""Shard Black format checks by top-level package under implementations/python.

N packages ⇒ N CI jobs. Completeness by enrollment of each package body.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from sugar_repo_root import resolve_repo_root  # noqa: E402

ROOT = resolve_repo_root()
PYTHON_ROOT = ROOT / "implementations" / "python"
SKIP = frozenset({"target", "bin", "__pycache__", ".venv", "conformance"})


def format_units() -> list[str]:
    """Repo-relative paths to top-level packages with .py files."""
    units: list[str] = []
    if not PYTHON_ROOT.is_dir():
        return units
    for path in sorted(PYTHON_ROOT.iterdir()):
        if not path.is_dir() or path.name in SKIP or path.name.startswith("."):
            continue
        if any(path.rglob("*.py")):
            units.append(path.relative_to(ROOT).as_posix())
    return units


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--emit-matrix-json", action="store_true")
    parser.add_argument("--print-roster", action="store_true")
    args = parser.parse_args(argv)
    units = format_units()
    if args.list or args.print_roster:
        for u in units:
            print(u)
        return 0
    if args.emit_matrix_json:
        # GitHub matrix needs short labels; use package basename as key
        pins = [Path(u).name for u in units]
        print(json.dumps({"package": pins}, separators=(",", ":")))
        return 0
    parser.error("pass --list / --emit-matrix-json / --print-roster")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
