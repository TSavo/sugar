#!/usr/bin/env python3
"""Desugar-inclusive, single-file reproducer with an explicit R(timeout) axis."""

from __future__ import annotations

import argparse
import json
import signal
import time
from pathlib import Path
from typing import Any, Sequence


class _FunctionTimeout(BaseException):
    pass


def _timeout(_signum, _frame) -> None:
    raise _FunctionTimeout()


def _desugar_one(
    function: Any,
    *,
    name: str,
    deadline_seconds: float = 0,
) -> dict[str, Any]:
    started = time.perf_counter()
    status = "clean"
    timed_out = False
    prior_handler = None
    try:
        if deadline_seconds > 0:
            prior_handler = signal.signal(signal.SIGALRM, _timeout)
            signal.setitimer(signal.ITIMER_REAL, deadline_seconds)
        function.sugar().desugar(None)
    except _FunctionTimeout:
        status = "timeout"
        timed_out = True
    except BaseException as exc:
        # ConstructionPanic is intentionally BaseException, not Exception.
        status = type(exc).__name__
    finally:
        if deadline_seconds > 0:
            signal.setitimer(signal.ITIMER_REAL, 0)
            assert prior_handler is not None
            signal.signal(signal.SIGALRM, prior_handler)
    span = function.line_col_span()
    return {
        "name": name,
        "line": span.start_line,
        "status": status,
        "timedOut": timed_out,
        "elapsedSeconds": round(time.perf_counter() - started, 6),
    }


def _report(
    *,
    file: str,
    functions: Sequence[dict[str, Any]],
    elapsed_s: float,
    deadline_seconds: float,
) -> dict[str, Any]:
    discovered = len(functions)
    completed = len(functions)
    timeouts = sum(bool(row["timedOut"]) for row in functions)
    construction_panics = sum(
        row["status"] == "ConstructionPanic" for row in functions
    )
    factoring_gaps = sum(
        row["status"] == "ExitSetFactoringGap" for row in functions
    )
    return {
        "schema": "sugar.desugar-repro.v1",
        "file": file,
        "deadlineSeconds": deadline_seconds,
        "elapsedSeconds": round(elapsed_s, 6),
        "discovered": discovered,
        "completed": completed,
        "R(timeout)": timeouts,
        "R(construction_panics)": construction_panics,
        "R(factoring_gaps)": factoring_gaps,
        "stableZero": (
            discovered > 0
            and discovered == completed
            and timeouts == 0
            and construction_panics == 0
            and factoring_gaps == 0
        ),
        "functions": list(functions),
    }


def _open_source_file(path: Path, *, root: Path):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_source_tree.reporter import CollectingReporter

    return open_source_file_for_construction(
        path,
        root=root,
        reporter=CollectingReporter(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--deadline", type=float, default=180)
    args = parser.parse_args()

    corpus = args.corpus
    if corpus is None:
        import pandas

        corpus = Path(pandas.__file__).resolve().parent
    path = (corpus / args.file).resolve()
    if not path.is_file():
        parser.error(f"missing file: {path}")

    started = time.perf_counter()
    source_file = _open_source_file(path, root=corpus)
    rows = []
    for index, function in enumerate(source_file.functions()):
        rows.append(
            _desugar_one(
                function,
                name=getattr(function, "name", f"function-{index}"),
                deadline_seconds=args.deadline,
            )
        )
    report = _report(
        file=args.file,
        functions=rows,
        elapsed_s=time.perf_counter() - started,
        deadline_seconds=args.deadline,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["stableZero"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
