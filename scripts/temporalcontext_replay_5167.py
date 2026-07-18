#!/usr/bin/env python3
"""Bounded owner replay for the five sealed #5121 TemporalContext representatives."""

from __future__ import annotations

import json
from pathlib import Path

import numpy
import pandas

from sugar_lift_py_tests.lift_rpc import audit_lift_file

FILES = (
    Path(pandas.__file__).parent / "tests/plotting/test_boxplot_method.py",
    Path(numpy.__file__).parent / "f2py/tests/util.py",
    Path(pandas.__file__).parent / "tests/series/methods/test_astype.py",
    Path(numpy.__file__).parent / "f2py/crackfortran.py",
    Path(pandas.__file__).parent / "tests/arrays/sparse/test_dtype.py",
)


def main() -> None:
    representatives = []
    total = 0
    files = 0
    for path in FILES:
        recovered = audit_lift_file(
            path.read_text(encoding="utf-8"),
            str(path),
            recover_panics=True,
        )
        rows = []
        for panic in recovered.panics:
            gap = panic.gap
            if gap.get("owner") != "TemporalContext":
                continue
            rows.append(
                {
                    "owner": gap["owner"],
                    "observed": gap["observed"],
                    "locus": gap["blame"],
                }
            )
        total += len(rows)
        files += bool(rows)
        representatives.append(
            {
                "file": str(path),
                "panic_count": len(recovered.panics),
                "effect_count": len(recovered.effects),
                "temporal_context": rows,
            }
        )
    print(
        json.dumps(
            {
                "python": __import__("platform").python_version(),
                "numpy": numpy.__version__,
                "pandas": pandas.__version__,
                "temporal_context_files": files,
                "temporal_context_terminals": total,
                "representatives": representatives,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
