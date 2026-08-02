#!/usr/bin/env python3
"""Deterministic file shards for the authoritative Python package suite.

WHY SHARDS, NOT ONE PROCESS
---------------------------
A single pytest over the whole package is one writer of one suite-report and
one long hold of a shared resource. Parallel CI jobs each own one shard: each
writes its own identity-bound report. Completeness is enrollment (all shards
attended), not aggregation into a shared hub.

SHARD LAW (LPT on measured prior)
---------------------------------
- Test *files* are the unit of assignment (not individual tests).
- k stays 8 (env tax; raising k only hits the max-file floor).
- Split key is LPT bin-packing on a content-addressed per-file cost prior
  (measured pytest wall seconds). Live by-count k=8 showed 1115s vs 45s
  shards (~25× imbalance) because 40 heavy files landed by path-index luck.
- No prior → honest equal-count degrade + JOB_LOG line; the run still WRITES
  the prior so the next is LPT.
- Empty shards are legal: they still attend with collected=0.

CANONICAL ORDER (stated, not silent)
------------------------------------
``suite-order=canonical`` is the collection order **within one shard's file
set**, not a single package-wide sequence. Discrimination arms reverse/shuffle
within a shard only. Cross-shard interleaving order is not a measured claim
under parallel jobs — there is no recombine step that would invent one.

Usage:
    python3 tools/python_package_suite_shards.py --list-files
    python3 tools/python_package_suite_shards.py --shard-index 3 --print-paths
    python3 tools/python_package_suite_shards.py --emit-matrix-json
    python3 tools/python_package_suite_shards.py --print-roster
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lpt_file_shards import (  # noqa: E402
    DEFAULT_SHARD_COUNT,
    ContentAddressedCostPrior,
    assign_files,
    narrate_assignment,
)

# 8 shards: env-sized fan-out. Split key is LPT, not path-index%8.
SHARD_COUNT = DEFAULT_SHARD_COUNT

# Relative to repo root. Collected pytest targets are files under this tree.
TESTS_REL = Path("implementations/python/sugar-lift-py-tests/tests")

# Paths that are never pytest targets (corpus / fixtures, not collected suite).
_SKIP_DIR_PARTS = frozenset({"vendor", "fixtures", "__pycache__"})


def repo_root_from(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "sugar-build.toml").is_file():
            return candidate
    raise SystemExit(f"cannot find sugar-build.toml above {here}")


def list_suite_test_files(repo_root: Path) -> list[str]:
    """Sorted repo-relative POSIX paths of suite test modules."""
    root = (repo_root / TESTS_REL).resolve()
    if not root.is_dir():
        raise SystemExit(f"suite tests tree missing: {root}")
    files: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(repo_root).as_posix()
        parts = set(path.relative_to(root).parts)
        if parts & _SKIP_DIR_PARTS:
            continue
        name = path.name
        if name == "conftest.py":
            continue
        # pytest collects test_*.py and *_test.py by default.
        if not (name.startswith("test_") or name.endswith("_test.py")):
            continue
        files.append(rel)
    return files


def _path_resolver(repo_root: Path, files: list[str]) -> dict[str, Path]:
    root = repo_root.resolve()
    return {rel: root / rel for rel in files if (root / rel).is_file()}


def assign_suite_shards(
    files: list[str],
    *,
    repo_root: Path,
    shard_count: int = SHARD_COUNT,
    narrate: bool = True,
):
    """LPT (or equal-count degrade) assignment for the suite file roster."""
    assignment = assign_files(
        files,
        shard_count=shard_count,
        path_resolver=_path_resolver(repo_root, files),
        prior=ContentAddressedCostPrior(),
    )
    if narrate:
        narrate_assignment(assignment, population="suite-pytest")
    return assignment


def shard_index_for(
    path: str,
    files: list[str],
    shard_count: int,
    *,
    repo_root: Path | None = None,
) -> int:
    root = repo_root if repo_root is not None else repo_root_from()
    assignment = assign_suite_shards(
        files, repo_root=root, shard_count=shard_count, narrate=False
    )
    for i, bucket in enumerate(assignment.bins):
        if path in bucket:
            return i
    raise SystemExit(f"path not in suite file roster: {path}")


def files_for_shard(
    files: list[str],
    shard_index: int,
    shard_count: int,
    *,
    repo_root: Path | None = None,
    narrate: bool = False,
) -> list[str]:
    if shard_count < 1:
        raise SystemExit("shard_count must be >= 1")
    if not (0 <= shard_index < shard_count):
        raise SystemExit(
            f"shard_index {shard_index} out of range for shard_count {shard_count}"
        )
    root = repo_root if repo_root is not None else repo_root_from()
    assignment = assign_suite_shards(
        files, repo_root=root, shard_count=shard_count, narrate=narrate
    )
    return list(assignment.bins[shard_index])


def roster_ids(shard_count: int) -> list[str]:
    return [f"shard-{i:02d}" for i in range(shard_count)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="checkout root (default: walk up to sugar-build.toml)",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=SHARD_COUNT,
        help=f"number of shards (default {SHARD_COUNT})",
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        default=None,
        help="0-based shard index for --print-paths",
    )
    parser.add_argument(
        "--list-files",
        action="store_true",
        help="print every suite test file (sorted)",
    )
    parser.add_argument(
        "--print-paths",
        action="store_true",
        help="print paths for --shard-index (pytest args); requires --shard-index",
    )
    parser.add_argument(
        "--print-roster",
        action="store_true",
        help="print expected shard ids (enrollment roster)",
    )
    parser.add_argument(
        "--emit-matrix-json",
        action="store_true",
        help='print GitHub Actions matrix JSON: {"shard":[0,1,...]}',
    )
    parser.add_argument(
        "--emit-shard-list-json",
        action="store_true",
        help="print JSON array of shard indices for nested matrix.order × shard",
    )
    parser.add_argument(
        "--mint-empty-report",
        action="store",
        default=None,
        metavar="PATH",
        help="write an identity-bound empty shard report to PATH (enrollment seat)",
    )
    parser.add_argument(
        "--suite-identity",
        default=None,
        help="environment-identity.json for --mint-empty-report",
    )
    parser.add_argument(
        "--suite-commit",
        default=None,
        help="measured commit for --mint-empty-report",
    )
    parser.add_argument(
        "--suite-binary-stamp",
        default=None,
        help="binary sourceStamp for --mint-empty-report",
    )
    parser.add_argument(
        "--suite-order",
        default="canonical",
        help="order field for --mint-empty-report",
    )
    parser.add_argument(
        "--emit-paths-for-cwd",
        action="store_true",
        help=(
            "like --print-paths but paths relative to implementations/python "
            "(workflow working-directory)"
        ),
    )
    args = parser.parse_args(argv)
    root = repo_root_from(args.repo_root)
    files = list_suite_test_files(root)

    if args.list_files:
        for path in files:
            print(path)
        return 0

    if args.print_roster:
        for shard_id in roster_ids(args.shard_count):
            print(shard_id)
        return 0

    if args.emit_matrix_json:
        matrix = {"shard": list(range(args.shard_count))}
        print(json.dumps(matrix, separators=(",", ":")))
        return 0

    if args.emit_shard_list_json:
        print(json.dumps(list(range(args.shard_count)), separators=(",", ":")))
        return 0

    if args.mint_empty_report is not None:
        if args.shard_index is None:
            parser.error("--mint-empty-report requires --shard-index")
        if not args.suite_identity or not args.suite_commit or not args.suite_binary_stamp:
            parser.error(
                "--mint-empty-report requires --suite-identity, --suite-commit, "
                "--suite-binary-stamp"
            )
        identity = json.loads(
            Path(args.suite_identity).read_text(encoding="utf-8")
        )
        stamp = (identity.get("sourceStamp") or {}).get("value")
        extras = (identity.get("dependencyAuthority") or {}).get(
            "testExtraInputHash"
        )
        shard = args.shard_index
        count = args.shard_count
        report = {
            "schemaVersion": 1,
            "label": (
                f"python-package-suite-{args.suite_order}-shard-{shard:02d}"
            ),
            "order": args.suite_order,
            "shuffleSeed": None,
            "shardIndex": shard,
            "shardCount": count,
            "pytestExitStatus": 5,
            "measuredCommit": args.suite_commit,
            "sourceStamp": stamp,
            "testExtraInputHash": extras,
            "environmentIdentityHash": identity.get("environmentIdentityHash"),
            "binarySourceStamp": args.suite_binary_stamp,
            "environmentIdentity": identity,
            "runnerIdentity": {"githubSha": args.suite_commit},
            "resourceTelemetry": {},
            "timing": {"wallSeconds": 0},
            "collectedNodeIds": [],
            "executedOrderNodeIds": [],
            "failedNodeIds": [],
            "errorNodeIds": [],
            "skippedNodeIds": [],
            "xfailedNodeIds": [],
            "xpassedNodeIds": [],
            "passedNodeIds": [],
            "collectionErrorNodeIds": [],
            "notReportedNodeIds": [],
            "counts": {
                "collected": 0,
                "passed": 0,
                "failed": 0,
                "error": 0,
                "skipped": 0,
                "xfailed": 0,
                "xpassed": 0,
                "collectionError": 0,
                "notReported": 0,
            },
            "conservation": {
                "collected": 0,
                "verdicts": 0,
                "executedOrder": 0,
                "buckets": {
                    "passed": 0,
                    "failed": 0,
                    "error": 0,
                    "skipped": 0,
                    "xfailed": 0,
                    "xpassed": 0,
                    "notReported": 0,
                },
                "collectionError": 0,
            },
        }
        out = Path(args.mint_empty_report)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"minted empty-shard report at {out}", file=sys.stderr)
        return 0

    if args.print_paths or args.emit_paths_for_cwd:
        if args.shard_index is None:
            parser.error("--print-paths requires --shard-index")
        # Narrate once per shard job: LPT vs equal-count + prior hit rate.
        chosen = files_for_shard(
            files,
            args.shard_index,
            args.shard_count,
            repo_root=root,
            narrate=True,
        )
        prefix = "implementations/python/"
        for path in chosen:
            if args.emit_paths_for_cwd:
                if not path.startswith(prefix):
                    raise SystemExit(f"path not under implementations/python: {path}")
                print(path[len(prefix) :])
            else:
                print(path)
        return 0

    parser.error(
        "pass one of --list-files / --print-paths / --print-roster / "
        "--emit-matrix-json / --emit-shard-list-json / --mint-empty-report"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
