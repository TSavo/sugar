#!/usr/bin/env python3
"""Emit checkout PYTHONPATH from the managed closure declaration.

Same source of truth as ``activate_checkout_import_roots``: the single
``ENV PYTHONPATH=...`` line in tools/sugar-build/Dockerfile. Used by the
python-test-environment action so process start finds first-party packages
in the SYNCED CHECKOUT before site-packages — before any import of
``sugar_lift_py_tests`` can pin a foreign copy into sys.modules.

Usage:
  python tools/python_test_checkout_pythonpath.py --repo-root .
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def checkout_pythonpath(repo_root: Path) -> str:
    dockerfile = repo_root / "tools/sugar-build/Dockerfile"
    matches = re.findall(
        r"^ENV PYTHONPATH=(.*)$",
        dockerfile.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if len(matches) != 1:
        raise SystemExit(
            f"expected one managed PYTHONPATH declaration in {dockerfile}, "
            f"found {len(matches)}"
        )
    prefix = "/workspace/sugar/"
    roots: list[str] = []
    for entry in matches[0].split(":"):
        if not entry.startswith(prefix):
            raise SystemExit(
                f"managed PYTHONPATH entry escaped the synced checkout: {entry}"
            )
        root = (repo_root / entry[len(prefix) :]).resolve()
        if not root.is_dir():
            raise SystemExit(
                f"managed PYTHONPATH entry does not exist in the synced "
                f"checkout: {root}"
            )
        roots.append(str(root))
    return ":".join(roots)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    sys.stdout.write(checkout_pythonpath(args.repo_root.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
