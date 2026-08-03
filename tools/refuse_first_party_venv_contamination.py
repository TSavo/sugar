#!/usr/bin/env python3
"""Refuse first-party distributions physically installed in this interpreter.

Ambient ``PYTHONPATH`` is deliberately excluded from the search.  The managed
CI environment imports first-party code from the checkout, while its immutable
venv may contain third-party distributions only.
"""

from __future__ import annotations

import importlib.metadata
import re
import sys
import sysconfig
from pathlib import Path


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def main(argv: list[str]) -> int:
    requested = {_canonical_name(value): value for value in argv}
    if not requested:
        raise SystemExit("usage: refuse_first_party_venv_contamination.py PACKAGE [...]")

    search_paths = sorted(
        {
            str(Path(path).resolve())
            for key in ("purelib", "platlib")
            if (path := sysconfig.get_path(key))
        }
    )
    contaminants: list[tuple[str, Path]] = []
    for distribution in importlib.metadata.distributions(path=search_paths):
        name = distribution.metadata.get("Name")
        if not name or _canonical_name(name) not in requested:
            continue
        metadata_path = Path(
            getattr(distribution, "_path", distribution.locate_file(""))
        ).resolve()
        contaminants.append((requested[_canonical_name(name)], metadata_path))

    if contaminants:
        for name, metadata_path in contaminants:
            print(
                f"::error::first-party package {name} present in venv; "
                f"metadata={metadata_path}; must resolve from checkout only",
                file=sys.stderr,
            )
        return 1

    print(
        "venv-contamination status=clean "
        f"searched={','.join(search_paths)} packages={','.join(requested.values())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
