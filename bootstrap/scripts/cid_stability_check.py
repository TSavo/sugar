#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "implementations/rust/libsugar/tests/fixtures/proofir"


def main() -> int:
    fixtures = sorted(FIXTURE_DIR.rglob("*.proofir.json"))
    if not fixtures:
        print(f"cid stability: no ProofIR fixtures under {FIXTURE_DIR}", file=sys.stderr)
        return 1

    result = subprocess.run(
        [
            "cargo",
            "test",
            "--manifest-path",
            "implementations/rust/Cargo.toml",
            "-p",
            "libsugar",
            "--test",
            "cid_stability",
            "--quiet",
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode

    print(f"cid stability: {len(fixtures)} fixtures, 0 mismatches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
