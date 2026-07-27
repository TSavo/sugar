#!/usr/bin/env python3
"""Run the authenticated 1,008-body producer-family attribution.

This entry point intentionally has no unauthenticated or build fallback.  Use
``bin/bpytest`` / ``sugar-bx.sh`` so CPython 3.12.13, NumPy 2.5.1, the canonical
pandas corpus, the Sugar binary, and #6464's shared demand table authenticate
before any body is measured.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.no_call_body_attribution import (
    run_authenticated_attribution,
)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[4]
    report = run_authenticated_attribution(repo_root)
    print(report.render(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
