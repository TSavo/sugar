#!/usr/bin/env python3
"""Run the authenticated 1,008 native-root producer-family attribution.

This entry point intentionally has no unauthenticated or build fallback.  Use
``bin/bpytest`` / ``sugar-bx.sh`` so CPython 3.12.13, NumPy 2.5.1, the canonical
pandas corpus, the Sugar binary, and #6464's shared demand table authenticate
before any body is measured.

Owners may pass ``--family Attribute`` (repeatable) to measure one fixed
denominator without constructing peer-family sources.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sugar_lift_py_tests.no_call_body_attribution import (

    ProducerFamily,
    run_authenticated_attribution,
)


from sugar_lift_py_tests.repo_root import resolve_repo_root

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--family",
        action="append",
        choices=[family.value for family in ProducerFamily],
        help="measure only this fixed-denominator producer family",
    )
    args = parser.parse_args()
    families = (
        frozenset(ProducerFamily(value) for value in args.family)
        if args.family
        else None
    )
    repo_root = resolve_repo_root()
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    import numpy
    import pandas

    corpus = authenticated_pandas_corpus()
    print(
        "authenticated execution environment: "
        f"python={sys.implementation.name}-{sys.version_info.major}."
        f"{sys.version_info.minor}.{sys.version_info.micro} "
        f"numpy={numpy.__version__} pandas={pandas.__version__} "
        f"corpusManifestCid={corpus.manifest_cid} fileCount={corpus.file_count}",
        flush=True,
    )
    report = run_authenticated_attribution(repo_root, families=families)
    print(report.render(), flush=True)
    return int(report.loud_failure_count != 0)


if __name__ == "__main__":
    raise SystemExit(main())
