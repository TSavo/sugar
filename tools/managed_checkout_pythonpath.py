#!/usr/bin/env python3
"""Managed first-party PYTHONPATH from the sugar-build Dockerfile declaration.

First-party Sugar packages resolve from the SYNCED CHECKOUT, never from a
wheel-installed site-packages copy of a different build. The managed closure
declares exactly one PYTHONPATH in ``tools/sugar-build/Dockerfile``; this tool
maps that declaration onto a real checkout so CI and authentication share one
root list.

This module is stdlib-only on purpose: the python-test-environment action must
export these roots BEFORE anything imports ``sugar_lift_py_tests``. Importing
the package to learn where the package lives is the ordering defect this
exists to prevent.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DOCKERFILE_REL = Path("tools/sugar-build/Dockerfile")
MANAGED_PREFIX = "/workspace/sugar/"


class ManagedCheckoutPythonpathError(RuntimeError):
    """The managed PYTHONPATH declaration is missing, escaped, or broken."""


def managed_checkout_import_roots(repo_root: Path) -> list[Path]:
    """Return absolute checkout import roots declared by the managed closure."""
    repo_root = repo_root.resolve()
    dockerfile = repo_root / DOCKERFILE_REL
    if not dockerfile.is_file():
        raise ManagedCheckoutPythonpathError(
            f"managed PYTHONPATH declaration missing: {dockerfile}"
        )
    matches = re.findall(
        r"^ENV PYTHONPATH=(.*)$",
        dockerfile.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if len(matches) != 1:
        raise ManagedCheckoutPythonpathError(
            f"expected one managed PYTHONPATH declaration in {dockerfile}, "
            f"found {len(matches)}"
        )
    roots: list[Path] = []
    for entry in matches[0].split(":"):
        if not entry.startswith(MANAGED_PREFIX):
            raise ManagedCheckoutPythonpathError(
                f"managed PYTHONPATH entry escaped the synced checkout: {entry}"
            )
        root = (repo_root / entry[len(MANAGED_PREFIX) :]).resolve()
        if not root.is_dir():
            raise ManagedCheckoutPythonpathError(
                f"managed PYTHONPATH entry does not exist in the synced checkout: "
                f"{root}"
            )
        roots.append(root)
    return roots


def managed_checkout_pythonpath(repo_root: Path) -> str:
    """Colon-joined absolute PYTHONPATH for the managed first-party roots."""
    return ":".join(str(root) for root in managed_checkout_import_roots(repo_root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Synced checkout root (directory containing sugar-build.toml).",
    )
    args = parser.parse_args(argv)
    try:
        print(managed_checkout_pythonpath(args.repo_root))
    except ManagedCheckoutPythonpathError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
