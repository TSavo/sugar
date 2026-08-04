# SPDX-License-Identifier: MIT OR Apache-2.0
"""Monorepo root door for tools/ and repo-level scripts (no package import).

Same law as ``sugar_lift_py_tests.repo_root.resolve_repo_root``: resolve by
asking for ``sugar-build.toml`` (env then walk), never ``Path(__file__).parents[N]``.
Kept free of package deps so ``python tools/foo.py`` from a bare checkout works.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Sequence

MARKER = "sugar-build.toml"
_ENV_KEYS: tuple[str, ...] = ("SUGAR_REPO_ROOT", "GITHUB_WORKSPACE")


class RepoRootUnresolved(RuntimeError):
    """The monorepo root could not be resolved; the marker was never found."""


def resolve_repo_root(
    *,
    start: Path | None = None,
    env: Mapping[str, str] | None = None,
    extra_starts: Sequence[Path] = (),
) -> Path:
    source = os.environ if env is None else env
    searched: list[str] = []

    for key in _ENV_KEYS:
        raw = source.get(key)
        if raw is None or not str(raw).strip():
            searched.append(f"env:{key}=<unset>")
            continue
        candidate = Path(str(raw)).expanduser().resolve()
        searched.append(f"env:{key}={candidate}")
        if candidate.is_dir() and (candidate / MARKER).is_file():
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
            if (current / MARKER).is_file():
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
