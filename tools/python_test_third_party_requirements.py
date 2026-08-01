#!/usr/bin/env python3
"""Emit third-party install specs for the immutable Python test environment.

First-party sugar-lift-* packages resolve from the SYNCED CHECKOUT via
PYTHONPATH (see tools/sugar-build/Dockerfile ENV PYTHONPATH and
activate_checkout_import_roots). They must NOT be wheel-installed into the
venv: that is what produced ExecutionEnvironmentMismatch on S0.1/S0.2
(site-packages lift vs checkout claim).

Third-party [test] deps still come from sugar-lift-py-tests[test] — the sole
dependency authority. This script only *names* those requirements so the
action can ``pip install --no-index --find-links wheelhouse`` without
installing first-party packages.

Usage:
  python tools/python_test_third_party_requirements.py --repo-root .
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

# Distribution names that are first-party monorepo packages. Never install
# these into the test venv; they load from checkout src roots.
FIRST_PARTY_DISTRIBUTIONS = frozenset(
    {
        "sugar-lift-py-tests",
        "sugar-lift-python-source",
        "sugar-source-tree",
        "sugar-lift-py-pytest-witness",
        "sugar-build-witness",
        "sugar-emit-python-hypothesis",
        "sugar-emit-python-pytest",
        "sugar-emit-python-unittest",
        "libsugar-py",
    }
)

AUTHORITY = "sugar-lift-py-tests"


def _normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _requirement_root_name(requirement: str) -> str:
    """Best-effort package name from a PEP 508 requirement string."""
    text = requirement.strip()
    for sep in ("[", " ", "<", ">", "=", "!", "~", ";", "@"):
        if sep in text:
            text = text.split(sep, 1)[0]
    return _normalize(text)


def third_party_requirements(repo_root: Path) -> list[str]:
    """Collect third-party requirements from first-party pyproject tables."""
    packages = (
        repo_root / "implementations/python/sugar-lift-py-tests/pyproject.toml",
        repo_root / "implementations/python/sugar-lift-python-source/pyproject.toml",
        repo_root / "implementations/python/sugar-source-tree/pyproject.toml",
    )
    seen: set[str] = set()
    ordered: list[str] = []
    for pyproject in packages:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data["project"]
        extras = project.get("optional-dependencies") or {}
        tables: list[list[str]] = [list(project.get("dependencies") or [])]
        # Authority package is sugar-lift-py-tests — [test] is the sole dep authority.
        if project.get("name") == AUTHORITY:
            tables.append(list(extras.get("test") or []))
        for table in tables:
            for requirement in table:
                root = _requirement_root_name(requirement)
                if root in FIRST_PARTY_DISTRIBUTIONS:
                    continue
                # Deduplicate by root name; keep first (pinned) occurrence.
                if root in seen:
                    continue
                seen.add(root)
                ordered.append(requirement.strip())
    if not ordered:
        raise SystemExit(
            f"no third-party requirements derived under {repo_root}; "
            "refusing an empty venv install"
        )
    return ordered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    for requirement in third_party_requirements(args.repo_root.resolve()):
        print(requirement)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
