#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Live instrument: Path(__file__).parents[N] outside package src.

R_repo_root_by_parents_count_outside_package_src — layout arithmetic residual
after the monorepo resolve door. Exit 1 while R > 0.

Buckets (outside ``sugar-lift-py-tests/src``):
  package tests/, package scripts/, repo tests/, tools/

Does not trust a hand list: rescans the tree every run.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

PAT = re.compile(
    r"(?:pathlib\.)?Path\(__file__\)(?:\.resolve\(\))?\.parents\[(\d+)\]"
)
BUCKETS = (
    ("package_tests", Path("implementations/python/sugar-lift-py-tests/tests")),
    ("package_scripts", Path("implementations/python/sugar-lift-py-tests/scripts")),
    ("repo_tests", Path("tests")),
    ("tools", Path("tools")),
)
SKIP_NAMES = frozenset(
    {
        "repo_root.py",
        "sugar_repo_root.py",
        "test_repo_root_door.py",
        "repo_root_parents_n_census.py",
    }
)


def scan(repo: Path) -> list[tuple[str, str, int, int, str]]:
    hits: list[tuple[str, str, int, int, str]] = []
    for bucket, rel in BUCKETS:
        base = repo / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if path.name in SKIP_NAMES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                for match in PAT.finditer(line):
                    hits.append(
                        (
                            bucket,
                            str(path.relative_to(repo)),
                            lineno,
                            int(match.group(1)),
                            line.strip()[:140],
                        )
                    )
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="monorepo root (default: walk from cwd for sugar-build.toml)",
    )
    args = parser.parse_args(argv)
    if args.repo is not None:
        repo = args.repo.resolve()
    else:
        # Prefer tools door so this instrument does not use parents[N]
        try:
            from sugar_repo_root import resolve_repo_root  # type: ignore

            repo = resolve_repo_root()
        except Exception:
            # Fallback walk from this file without a fixed index
            here = Path(__file__).resolve()
            repo = None
            for parent in here.parents:
                if (parent / "sugar-build.toml").is_file():
                    repo = parent
                    break
            if repo is None:
                print("FAIL: cannot resolve monorepo root", file=sys.stderr)
                return 2

    hits = scan(repo)
    by_bucket = Counter(h[0] for h in hits)
    print(f"R_repo_root_by_parents_count_outside_package_src={len(hits)}")
    for bucket, _rel in BUCKETS:
        print(f"  {bucket}={by_bucket.get(bucket, 0)}")
    for bucket, path, line, n, text in hits:
        print(f"{path}:{line}: parents[{n}] {text}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
