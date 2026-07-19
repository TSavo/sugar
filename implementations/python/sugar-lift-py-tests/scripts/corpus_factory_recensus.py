from __future__ import annotations

import argparse
import ast
import importlib.metadata
import importlib.util
import json
import logging
import signal
import sys
from collections import Counter
from pathlib import Path

from sugar_lift_py_tests.audit_only import collect_factory_panic
from sugar_lift_py_tests.idd.factory_walk_unclassified_locus import (
    project_unclassified_locus,
    shape_split_unclassified,
)
from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRedRowDto
from sugar_lift_py_tests.lift_rpc import lift_file_payload

PACKAGES = ("numpy", "pandas")
UNIVERSE_REQUEST = "callee universe coverage"
FILE_TIMEOUT_SECONDS = 30
COMPACT_LOCUS_LIMIT = 200


class FileLiftTimeout(BaseException):
    pass


def _timeout_file(_signum, _frame) -> None:
    raise FileLiftTimeout(f"lift exceeded {FILE_TIMEOUT_SECONDS}s")


def package_root(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    assert spec is not None and spec.origin is not None
    return Path(spec.origin).resolve().parent


def python_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.py") if "__pycache__" not in path.parts
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("packages", nargs="*", choices=PACKAGES)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        parser.error("shard index must be in [0, shard count)")
    packages = tuple(args.packages) or PACKAGES
    logging.disable(logging.CRITICAL)
    signal.signal(signal.SIGALRM, _timeout_file)
    versions = {package: importlib.metadata.version(package) for package in packages}
    counts: Counter[str] = Counter()
    red_statuses: Counter[str] = Counter()
    fatal_types: Counter[str] = Counter()
    universe_callees: Counter[str] = Counter()
    universe_by_package: Counter[str] = Counter()
    universe_examples: list[dict[str, object]] = []
    fatal_examples: list[dict[str, object]] = []
    factory_walk_unclassified_rows: list[dict[str, object]] = []

    all_paths = [
        (package, root, path)
        for package in packages
        for root in (package_root(package),)
        for path in python_files(root)
    ]
    paths = [
        item
        for index, item in enumerate(all_paths)
        if index % args.shard_count == args.shard_index
    ]
    for index, (package, root, path) in enumerate(paths, start=1):
        counts["files_total"] += 1
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = path.read_text(encoding="utf-8", errors="replace")
        rel = f"{package}/{path.relative_to(root).as_posix()}"
        try:
            signal.setitimer(signal.ITIMER_REAL, FILE_TIMEOUT_SECONDS)
            tree = ast.parse(source, filename=rel)
            assertion_count = sum(
                isinstance(node, ast.Assert) for node in ast.walk(tree)
            )
            counts["assertions_total"] += assertion_count
            if assertion_count == 0:
                counts["files_without_assertions_skipped"] += 1
                continue
            counts["files_with_assertions"] += 1
            payload, panic_gap = collect_factory_panic(
                rel,
                lambda: lift_file_payload(source, rel),
            )
            if panic_gap is not None:
                counts["files_fatal"] += 1
                fatal_types["FactoryPanic"] += 1
                if len(fatal_examples) < 50:
                    fatal_examples.append(
                        {
                            "file": rel,
                            "error_type": "FactoryPanic",
                            "reason": panic_gap.message.splitlines()[-1][:500],
                            "gap": panic_gap.info,
                        }
                    )
                continue
            assert payload is not None
        except KeyboardInterrupt:
            raise
        except (Exception, FileLiftTimeout) as error:
            counts["files_fatal"] += 1
            fatal_types[type(error).__name__] += 1
            if len(fatal_examples) < 50:
                fatal_examples.append(
                    {
                        "file": rel,
                        "error_type": type(error).__name__,
                        "reason": (str(error).splitlines() or [repr(error)])[-1][:500],
                    }
                )
            continue
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)

        counts["files_completed"] += 1
        counts["facts_emitted"] += len(payload.ir)
        counts["assertion_surface_audits"] += len(payload.assertion_surface_audits)
        coverage = payload.lift_coverage or {}
        for key, value in coverage.items():
            if isinstance(value, int):
                counts[f"lift_coverage.{key}"] += value

        for row in payload.factory_walk:
            status_value = getattr(
                getattr(row, "status", None), "value", None
            ) or str(getattr(row, "status", "") or "")
            # Permanent product-completeness axis (#5252): unclassified /
            # wire-unresolved walk rows are honest red residue, not success.
            # Retain a row-addressable locus for shape-split drain.
            if status_value in {"unclassified", "unresolved"}:
                counts["R_factory_walk_unclassified"] += 1
                locus = project_unclassified_locus(row)
                if locus is not None:
                    factory_walk_unclassified_rows.append(locus)
            if not isinstance(row, FactoryWalkRedRowDto):
                continue
            counts["factory_walk_red_total"] += 1
            red_statuses[row.status.value] += 1
            if row.requested_role != UNIVERSE_REQUEST:
                continue
            counts["universe_absence_gaps"] += 1
            universe_by_package[package] += 1
            universe_callees[row.ast_kind] += 1
            if len(universe_examples) < 100:
                universe_examples.append(
                    {
                        "file": row.file,
                        "line": row.line,
                        "callee": row.ast_kind,
                        "reason": row.reason,
                    }
                )

        if index % 100 == 0:
            print(f"measured {index}/{len(paths)} files", file=sys.stderr)

    r_unclassified = int(counts.get("R_factory_walk_unclassified", 0))
    retained_loci = factory_walk_unclassified_rows
    if args.compact and len(retained_loci) > COMPACT_LOCUS_LIMIT:
        retained_loci = retained_loci[:COMPACT_LOCUS_LIMIT]
    report = {
        "package_versions": versions,
        "shard": {"index": args.shard_index, "count": args.shard_count},
        # Permanent baseline-free floor (#5252). Separate red axis from
        # crashes / bare exceptions / timeouts / file fatals.
        # Row-addressable loci enable offline shape-split (not just R).
        "R_factory_walk_unclassified": r_unclassified,
        "factory_walk_statuses": {
            "unclassified": r_unclassified,
            **{
                status: count
                for status, count in sorted(red_statuses.items())
                if status != "unclassified"
            },
        },
        "factory_walk_unclassified_shape_split": shape_split_unclassified(
            factory_walk_unclassified_rows
        ),
        "factory_walk_unclassified_rows": retained_loci,
        "counts": dict(sorted(counts.items())),
        "factory_walk_red_statuses": dict(sorted(red_statuses.items())),
        "fatal_types": dict(sorted(fatal_types.items())),
        "universe_absence_by_package": dict(sorted(universe_by_package.items())),
    }
    if args.compact and r_unclassified > COMPACT_LOCUS_LIMIT:
        report["factory_walk_unclassified_rows_truncated"] = True
        report["factory_walk_unclassified_rows_retained"] = COMPACT_LOCUS_LIMIT
    if not args.compact:
        report.update(
            {
                "universe_absence_callees": dict(
                    sorted(
                        universe_callees.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ),
                "universe_absence_examples_first_100": universe_examples,
                "fatal_examples_first_50": fatal_examples,
            }
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
