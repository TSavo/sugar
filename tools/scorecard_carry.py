#!/usr/bin/env python3
"""The main scorecard's suite totals, and its carried federation verdict.

    scorecard_carry.py summarize --label L --out F [--result F] SUMMARY...
    scorecard_carry.py verdict key|get|put ...

WHY THIS EXISTS

The main scorecard (.github/workflows/main-scorecard.yml) runs the package
suite and the solver twins on shards; each pytest writes a summary of every
node ID it collected and its outcome buckets (tools/scorecard_carry_pytest.py).
``summarize`` merges those summaries into the totals the row posts.

NOTHING IS CARRIED (#8416, 2026-11-16)

This module used to record, per pytest test and per pandas board file, the
fingerprint of every first-party function it executed (a ``sys.monitoring``
PY_START recorder re-instrumenting live bytecode on every test) and to carry
unchanged results forward from a store on the runner host. It carried
nothing: every row said ``carried=suite:0`` with every test opaque to it, and
it was the prime suspect for the shards' intermittent segfaults (exit 139,
runs 43832361876 and 43841836171: shallow pure-Python crash points in
unrelated tests, on different runners, with the engine watchdog thread live).
The recorder, the store and the board's carry are deleted. Every test of
every shard runs; the row's ``rerun=`` is each measure's total and its
``carried=`` is 0.

THE FEDERATION VERDICT

The federation example is a chain of subprocesses. A PASS is carried only
while every input outside docs/ and the other examples is byte-identical
(``verdict key``: git tree hashes plus the interpreter and installed
distributions); a FAIL is never carried.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

MECHANISM = "sugar-scorecard-verdict/v1"
BUCKETS = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")
SUMMARY_SCHEMA = "sugar-scorecard-summary/v2"

_HERE = Path(__file__).resolve()


def narrate(message: str) -> None:
    print(message, flush=True)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _write_json(path: str | os.PathLike[str], obj: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")


# ------------------------------------------------------------------- totals


def _path_suffixes(paths: Iterable[str]) -> set[str]:
    """Every whole-component suffix of each path (a/b/c -> a/b/c, b/c, c)."""
    out: set[str] = set()
    for path in paths:
        parts = path.strip().strip("/").split("/")
        for i in range(len(parts)):
            out.add("/".join(parts[i:]))
    return out


def summarize(
    inputs: Iterable[str | os.PathLike[str]],
    label: str,
    filtered: Iterable[str | os.PathLike[str]] = (),
    only_files: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Merge pytest summaries into totals.

    ``filtered`` summaries contribute only the node IDs whose test file is one
    of ``only_files`` (paths relative to any ancestor of pytest's rootdir: a
    node ID's file matches when it is a whole-component suffix of a listed
    path). The solver twins inside the suite tree are counted this way from
    the suite's own results instead of being run a second time (#8416).
    """
    items: dict[str, list[str]] = {}
    errors: set[str] = set()
    read = 0
    keep_files = _path_suffixes(only_files or ())

    def wanted(nodeid: str) -> bool:
        return nodeid.split("::", 1)[0] in keep_files

    sources = [(path, False) for path in inputs] + [(path, True) for path in filtered]
    for path, is_filtered in sources:
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        read += 1
        for nodeid, entry in (doc.get("items") or {}).items():
            if is_filtered and not wanted(nodeid):
                continue
            items.setdefault(nodeid, list((entry or {}).get("buckets") or []))
        errors.update(
            nodeid
            for nodeid in (doc.get("collectionErrors") or [])
            if not is_filtered or wanted(nodeid)
        )
    counts = {bucket: 0 for bucket in BUCKETS}
    not_reported = 0
    for buckets in items.values():
        if not buckets:
            not_reported += 1
        for bucket in buckets:
            if bucket in counts:
                counts[bucket] += 1
    return {
        "schema": "sugar-scorecard-totals/v2",
        "label": label,
        "inputsRead": read,
        "counts": {
            "collected": len(items),
            **counts,
            "collectionError": len(errors),
            "notReported": not_reported,
        },
        "collectionErrorNodeIds": sorted(errors),
        "failedNodeIds": sorted(
            nodeid
            for nodeid, buckets in items.items()
            if "failed" in buckets or "error" in buckets
        ),
    }


def cmd_summarize(args: argparse.Namespace) -> int:
    only_files: list[str] | None = None
    if args.only_files:
        only_files = [
            line.strip()
            for line in Path(args.only_files).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    totals = summarize(args.inputs, args.label, args.filtered, only_files)
    _write_json(args.out, totals)
    c = totals["counts"]
    if args.result:
        # The scorecard's view (tools/main_scorecard_post.py --put).
        t0 = os.environ.get("JOB_T0", "")
        _write_json(
            args.result,
            {
                "measured": bool(totals["inputsRead"]) and c["collected"] > 0,
                "passed": c["passed"],
                "total": c["collected"],
                "failed": c["failed"] + c["error"] + c["collectionError"],
                "jobWallSeconds": int(time.time() - float(t0)) if t0 else None,
            },
        )
    # Every collected test ran: rerun is the whole count, nothing is carried.
    narrate(
        f"SCORECARD CARRY TOTALS label={args.label} collected={c['collected']} "
        f"passed={c['passed']} failed={c['failed']} error={c['error']} "
        f"collectionError={c['collectionError']} rerun={c['collected']} "
        f"carried=0 opaque=0"
    )
    for nodeid in totals["failedNodeIds"]:
        narrate(f"SCORECARD FAILED label={args.label} {nodeid}")
    for nodeid in totals["collectionErrorNodeIds"]:
        narrate(f"SCORECARD COLLECTION ERROR label={args.label} {nodeid}")
    return 0


# ------------------------------------------------------------------ verdict


def env_key(extra: Mapping[str, Any]) -> str:
    """Interpreter + platform + third-party distributions + this module."""
    import importlib.metadata
    import platform
    import sysconfig

    paths = sorted({sysconfig.get_paths()["purelib"], sysconfig.get_paths()["platlib"]})
    dists = sorted(
        {
            f"{(dist.metadata['Name'] or '?').lower()}=={dist.version}"
            for dist in importlib.metadata.distributions(path=paths)
        }
    )
    material = {
        "mechanism": MECHANISM,
        "module": _sha(_HERE.read_bytes()),
        "python": sys.version,
        "cacheTag": sys.implementation.cache_tag,
        "platform": sys.platform,
        "machine": platform.machine(),
        "distributions": dists,
        "extra": {str(k): str(extra[k]) for k in sorted(extra)},
    }
    return _sha(canonical(material))[:24]


def tree_key(includes: list[str], excludes: list[str], extras: list[str]) -> str:
    """A coarse content key for a measure whose dependencies are not traced."""
    top = subprocess.run(
        ["git", "ls-tree", "HEAD"], capture_output=True, text=True, check=True
    ).stdout
    material = [line for line in top.splitlines() if line.split("\t")[-1] not in excludes]
    for path in includes:
        material.append(
            path
            + "="
            + subprocess.run(
                ["git", "rev-parse", f"HEAD:{path}"], capture_output=True, text=True, check=True
            ).stdout.strip()
        )
    material.extend(extras)
    material.append(env_key({"tool": "verdict"}))
    return _sha("\n".join(material).encode("utf-8"))[:32]


def cmd_verdict(args: argparse.Namespace) -> int:
    path = Path(args.store) / "verdicts" / args.name / f"{args.key}.json"
    if args.action == "key":
        print(tree_key(args.include, args.exclude, args.extra))
        return 0
    if args.action == "get":
        try:
            print(json.loads(path.read_text(encoding="utf-8"))["verdict"])
        except (OSError, ValueError, KeyError):
            return 3
        return 0
    _write_json(path, {"verdict": args.value, "recordedAt": time.time()})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    summ = sub.add_parser("summarize", help="merge pytest summaries into totals")
    summ.add_argument("--out", required=True)
    summ.add_argument("--label", default="suite")
    summ.add_argument("--result", default=None, help="also write the scorecard result")
    summ.add_argument(
        "--filtered",
        action="append",
        default=[],
        help="a summary counted only for the node IDs of --only-files (repeatable)",
    )
    summ.add_argument("--only-files", default=None, help="test files kept from --filtered")
    summ.add_argument("inputs", nargs="*")
    summ.set_defaults(func=cmd_summarize)

    verdict = sub.add_parser("verdict", help="carry a PASS keyed by a tree key")
    verdict.add_argument("action", choices=["key", "get", "put"])
    verdict.add_argument("--store", default="")
    verdict.add_argument("--name", default="")
    verdict.add_argument("--key", default="")
    verdict.add_argument("--value", default="")
    verdict.add_argument("--include", action="append", default=[])
    verdict.add_argument("--exclude", action="append", default=[])
    verdict.add_argument("--extra", action="append", default=[])
    verdict.set_defaults(func=cmd_verdict)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
