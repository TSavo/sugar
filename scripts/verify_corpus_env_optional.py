"""Assert every `name==version` line of a pin file is installed at exactly that version.

Usage: <venv python> scripts/verify_corpus_env_optional.py scripts/corpus-env-optional.txt

Reads distribution metadata only (imports none of the packages), so a missing or
drifted optional package fails the corpus bootstrap by name instead of passing
silently. Exit 0 prints OPTIONAL_OK; otherwise exit 1 names each offender.
"""

from __future__ import annotations

import importlib.metadata as md
import sys
from pathlib import Path


def main(pin_file: str) -> int:
    pins: list[tuple[str, str]] = []
    for raw in Path(pin_file).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, sep, version = line.partition("==")
        if not sep or not name.strip() or not version.strip():
            print(f"unpinned line in {pin_file}: {raw!r}", file=sys.stderr)
            return 1
        pins.append((name.strip(), version.strip()))
    if not pins:
        print(f"no pins in {pin_file}", file=sys.stderr)
        return 1
    offenders: list[str] = []
    for name, version in pins:
        try:
            observed = md.version(name)
        except md.PackageNotFoundError:
            offenders.append(f"{name}=={version}: not installed")
            continue
        if observed != version:
            offenders.append(f"{name}=={version}: observed {observed}")
    if offenders:
        print(
            f"corpus optional set does not hold ({len(offenders)} of {len(pins)}):",
            file=sys.stderr,
        )
        for offender in offenders:
            print(f"  {offender}", file=sys.stderr)
        return 1
    print(f"OPTIONAL_OK {len(pins)} packages")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
