#!/usr/bin/env python3
"""generate_golden.py -- emit the committed golden corpus artifact.

Runs memento_walker.py over every corpus/*.py file (in sorted filename
order, so the artifact is stable across runs) and writes a single JSONL
file: golden_mementos.jsonl. Each line is one (file, node_path, kind,
span, cid) record. This is the pinned artifact any backend adapter must
reproduce byte-identically (per #5940) -- generated on host python3.12.3
unless regenerated explicitly.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).parent
CORPUS_DIR = HERE / "corpus"
OUT_PATH = HERE / "golden_mementos.jsonl"


def main() -> int:
    files = sorted(CORPUS_DIR.glob("*.py"))
    if not files:
        print("no corpus files found", file=sys.stderr)
        return 1
    lines = []
    for f in files:
        result = subprocess.run(
            [sys.executable, str(HERE / "memento_walker.py"), str(f)],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("#"):
                continue
            lines.append(line)
    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} records from {len(files)} files to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
