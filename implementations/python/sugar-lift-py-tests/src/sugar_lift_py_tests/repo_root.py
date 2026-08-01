# SPDX-License-Identifier: MIT OR Apache-2.0
"""ONE door: resolve the Sugar monorepo root by asking, never by counting.

``Path(__file__).resolve().parents[N]`` encodes "the root is exactly N levels
up" as a magic integer. When the package is installed into a venv's
site-packages that integer is simply wrong — and it does not crash at the
count; it resolves to a REAL BUT WRONG path (e.g. the python-test-environment
temp dir). Authentication then FileNotFoundError-s far away wearing the
costume of a corpus failure.

The missing object is a root that cannot be constructed by layout arithmetic.
This door RESOLVES by:

1. explicit environment binding (``SUGAR_REPO_ROOT``, then ``GITHUB_WORKSPACE``
   if it actually contains the marker);
2. walking up from a known anchor (default: process cwd) until the marker file
   ``sugar-build.toml`` is found.

It REFUSES LOUDLY, naming the marker and every place it looked, when the root
cannot be found. Never a silent fallback to a plausible directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Sequence

MARKER = "sugar-build.toml"
# Explicit seats first. GITHUB_WORKSPACE is the CI checkout; SUGAR_REPO_ROOT is
# the general override for non-checkout layouts (site-packages installs).
_ENV_KEYS: tuple[str, ...] = ("SUGAR_REPO_ROOT", "GITHUB_WORKSPACE")


class RepoRootUnresolved(RuntimeError):
    """The monorepo root could not be resolved; the marker was never found."""


def _has_marker(directory: Path) -> bool:
    return (directory / MARKER).is_file()


def _env_candidate(env: Mapping[str, str], key: str) -> Path | None:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return None
    return Path(str(raw)).expanduser().resolve()


def resolve_repo_root(
    *,
    start: Path | None = None,
    env: Mapping[str, str] | None = None,
    extra_starts: Sequence[Path] = (),
) -> Path:
    """Resolve the Sugar monorepo root, or refuse naming what was searched.

    Parameters
    ----------
    start:
        First walk anchor. Defaults to the process current working directory.
    env:
        Environment map. Defaults to ``os.environ``.
    extra_starts:
        Additional walk anchors (e.g. a known file path's parents) tried after
        ``start``. Each is walked upward independently; none is used as a
        counted index into a fixed layout.
    """
    source = os.environ if env is None else env
    searched: list[str] = []

    for key in _ENV_KEYS:
        candidate = _env_candidate(source, key)
        if candidate is None:
            searched.append(f"env:{key}=<unset>")
            continue
        searched.append(f"env:{key}={candidate}")
        if candidate.is_dir() and _has_marker(candidate):
            return candidate

    anchors: list[Path] = []
    primary = Path.cwd().resolve() if start is None else Path(start).resolve()
    anchors.append(primary)
    for extra in extra_starts:
        resolved = Path(extra).resolve()
        if resolved not in anchors:
            anchors.append(resolved)

    for anchor in anchors:
        current = anchor if anchor.is_dir() else anchor.parent
        seen: set[Path] = set()
        while current not in seen:
            seen.add(current)
            searched.append(f"walk:{current}")
            if _has_marker(current):
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent

    raise RepoRootUnresolved(
        "cannot resolve Sugar monorepo root: "
        f"looked for {MARKER!r} via explicit env ({', '.join(_ENV_KEYS)}) "
        f"and by walking up from anchors; searched: {searched}. "
        f"Set SUGAR_REPO_ROOT to the checkout that contains {MARKER}, "
        "or run with that checkout as the working directory."
    )


def sugar_lift_py_tests_package_root(repo_root: Path | None = None) -> Path:
    """The checkout package root for sugar-lift-py-tests (owns pyproject.toml).

    Never derived from site-packages layout. Always under the monorepo root.
    """
    root = repo_root if repo_root is not None else resolve_repo_root()
    package = (root / "implementations" / "python" / "sugar-lift-py-tests").resolve()
    if not (package / "pyproject.toml").is_file():
        raise RepoRootUnresolved(
            "cannot locate sugar-lift-py-tests package root: "
            f"expected pyproject.toml at {package / 'pyproject.toml'} "
            f"under resolved monorepo root {root}"
        )
    return package
