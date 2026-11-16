#!/usr/bin/env python3
"""Pack the scorecard's test files onto its shards, and check every shard reported.

    main_scorecard_shard_plan.py pack  --cwd PY --suite F --twins F --shard-count N --out PLAN
    main_scorecard_shard_plan.py check --plan PLAN --results DIR --result suite=F --result twins=F

WHY THIS EXISTS (#8416)

The main scorecard's suite shards each re-derived their files from the whole
suite roster, and the LPT cost prior they consulted lived in the job's
workspace, which every checkout wiped: every run fell back to equal counts
(68 files a shard) and the shards' walls ranged from 2 to 17 minutes. The
solver twins were a separate 20-minute job that re-ran 50 files the suite
shards had already run.

``pack`` runs once, in the plan job. It takes every file that runs -- the
suite's, and the twin files outside the suite tree (the twins
in the suite tree are read from the suite's own results) -- and packs them
onto the shards with tools/lpt_file_shards.py on the shared prior
(SUGAR_LPT_PRIOR_DIR, written by tools/scorecard_carry_pytest.py after every
pytest with each file's measured wall seconds). Files with no prior yet are
estimated from their size, as lpt_file_shards does.

Writes, for each shard i, ``<out>/shard-<ii>.suite.txt`` and
``<out>/shard-<ii>.twins.txt`` (paths relative to implementations/python,
one per line; either may be empty), and ``<out>/shards.json``: how many
shards the plan made and, per shard and population, how many files and about
how many tests it was planned to run (from the ledger of each file's last
measured test count).

A LOST SHARD IS NEVER A SMALLER TOTAL (#8416, run 43832361876)

Suite shard 2 failed in its toolchain step and shard 1's pytest died with
SIGSEGV (exit 139); neither wrote a pytest summary, and the join summed the six
that did: the row said ``suite=4209/4212`` as if measured, with about 1450
tests silently missing, and the alarm (failing counts only) said OK.

``check`` runs in the job that posts the suite and twins numbers. A shard
that was planned files of a population and left no pytest summary for it, or
whose pytest exited other than 0 (passed), 1 (tests failed) or 5 (no tests
collected), or that ran nothing while
tests were planned, did not measure. That population's result is then
rewritten as unmeasured with an ``incomplete:`` note naming the shards. The
twins in the suite tree are counted from the suite's results, so a lost suite
shard makes the twins unmeasured too. A population whose every shard reported
updates the ledger.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

POPULATIONS = ("suite", "twins")
# pytest exit statuses after which the shard's tests ran: 0 all passed,
# 1 some failed, 5 no tests collected.
RAN = {0, 1, 5}
PLAN_SCHEMA = "sugar-main-scorecard-shards/v1"


def read_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_json(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def cmd_pack(args: argparse.Namespace) -> int:
    from lpt_file_shards import ContentAddressedCostPrior, assign_files, narrate_assignment

    keys: list[str] = []
    resolver: dict[str, Path] = {}
    for population, listing in (("suite", args.suite), ("twins", args.twins)):
        for rel in read_lines(listing):
            key = f"{population}\t{rel}"
            if key in resolver:
                continue
            keys.append(key)
            resolver[key] = (args.cwd / rel).resolve()

    assignment = assign_files(
        keys,
        shard_count=args.shard_count,
        path_resolver={k: p for k, p in resolver.items() if p.is_file()},
        prior=ContentAddressedCostPrior(),
    )
    narrate_assignment(assignment, population="main-scorecard")

    ledger = (read_json(args.ledger) or {}).get("files", {}) if args.ledger else {}
    args.out.mkdir(parents=True, exist_ok=True)
    shards = []
    for index in range(args.shard_count):
        bucket = assignment.bins[index] if index < len(assignment.bins) else []
        by_population: dict[str, list[str]] = {"suite": [], "twins": []}
        for key in bucket:
            population, rel = key.split("\t", 1)
            by_population[population].append(rel)
        entry: dict[str, object] = {"index": index}
        tests_planned = 0
        for population, rels in by_population.items():
            (args.out / f"shard-{index:02d}.{population}.txt").write_text(
                "".join(f"{rel}\n" for rel in sorted(rels)), encoding="utf-8"
            )
            counts = [ledger.get(f"{population}\t{rel}") for rel in rels]
            planned = sum(n for n in counts if isinstance(n, int))
            tests_planned += planned
            entry[population] = {
                "files": len(rels),
                "testsPlanned": planned,
                "filesWithoutCount": sum(1 for n in counts if not isinstance(n, int)),
            }
        shards.append(entry)
        loads = assignment.estimated_loads or ()
        load = loads[index] if index < len(loads) else 0.0
        print(
            f"SCORECARD SHARD PLAN shard={index} suite_files={len(by_population['suite'])} "
            f"twins_files={len(by_population['twins'])} tests_planned~{tests_planned} "
            f"estimated_s={load:.1f} mode={assignment.mode}",
            flush=True,
        )
    write_json(args.out / "shards.json", {"schema": PLAN_SCHEMA, "shardCount": args.shard_count, "shards": shards})
    return 0


def shard_loss(results: Path, population: str, index: int, planned: dict) -> str | None:
    """Why shard ``index`` did not measure ``population``, or None when it did."""
    tag = f"{index:02d}"
    exit_file = results / population / f"shard-{tag}.exit"
    try:
        exit_text = exit_file.read_text(encoding="utf-8").strip()
    except OSError:
        exit_text = ""
    summary = read_json(results / population / f"shard-{tag}.json")
    if summary is None:
        if exit_text:
            return f"pytest exit {exit_text}, no results"
        return "left no results (the job failed before its tests ran)"
    status = summary.get("pytestExitStatus")
    if status not in RAN:
        return f"pytest exit {status} (interrupted before its tests ran)"
    if not summary.get("items") and not summary.get("collectionErrors") and planned.get("testsPlanned", 0) > 0:
        return "ran no tests"
    return None


def cmd_check(args: argparse.Namespace) -> int:
    targets: dict[str, Path] = {}
    for item in args.result:
        population, _, path = item.partition("=")
        if population not in POPULATIONS or not path:
            sys.exit(f"::error::bad --result {item!r}")
        targets[population] = Path(path)

    lost: dict[str, list[str]] = {population: [] for population in POPULATIONS}
    plan = read_json(args.plan / "shards.json")
    if plan is None or not isinstance(plan.get("shards"), list):
        for population in POPULATIONS:
            lost[population].append(f"no shard plan at {args.plan / 'shards.json'}")
        shards: list = []
    else:
        shards = plan["shards"]
    for shard in shards:
        index = int(shard.get("index", -1))
        for population in POPULATIONS:
            planned = shard.get(population) or {}
            if not planned.get("files"):
                continue
            why = shard_loss(args.results, population, index, planned)
            if why is not None:
                uncounted = planned.get("filesWithoutCount", 0)
                lost[population].append(
                    f"shard {index} {why}: {planned['files']} {population} files, "
                    f"~{planned.get('testsPlanned', 0)} tests planned"
                    + (f" (+{uncounted} files not yet counted)" if uncounted else "")
                )
    if lost["suite"]:
        lost["twins"].append("suite shards lost (the twins in the suite tree are counted from them)")

    shard_count = plan.get("shardCount") if plan else "?"
    for population in POPULATIONS:
        if not lost[population]:
            print(f"SCORECARD SHARD CHECK {population}: all {shard_count} shard(s) reported")
            continue
        note = "incomplete: " + "; ".join(lost[population])
        print(f"::error::SCORECARD SHARD CHECK {population}: {note}")
        target = targets.get(population)
        if target is not None:
            previous = read_json(target) or {}
            write_json(
                target,
                {
                    "measured": False,
                    "note": note,
                    "jobWallSeconds": previous.get("jobWallSeconds"),
                    "partial": {
                        "passed": previous.get("passed"),
                        "total": previous.get("total"),
                        "failed": previous.get("failed"),
                    },
                },
            )

    if args.ledger:
        update_ledger(args.ledger, args.results, [p for p in POPULATIONS if not lost[p]])
    return 0


def update_ledger(ledger_path: Path, results: Path, populations: list[str]) -> None:
    """Each run test file's test count, from the shards of complete populations."""
    if not populations:
        return
    ledger = read_json(ledger_path) or {}
    files = ledger.get("files") if isinstance(ledger.get("files"), dict) else {}
    for population in populations:
        counts: dict[str, int] = {}
        for summary_path in sorted((results / population).glob("shard-*.json")):
            summary = read_json(summary_path) or {}
            for nodeid in summary.get("items") or {}:
                rel = nodeid.split("::", 1)[0]
                counts[rel] = counts.get(rel, 0) + 1
        for rel, n in counts.items():
            files[f"{population}\t{rel}"] = n
    try:
        write_json(ledger_path, {"schema": "sugar-main-scorecard-test-counts/v1", "files": files})
    except OSError as exc:
        print(f"::warning::could not write the test-count ledger {ledger_path}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    pack = sub.add_parser("pack", help="pack the files to run onto the shards")
    pack.add_argument("--cwd", type=Path, required=True, help="implementations/python")
    pack.add_argument("--suite", type=Path, required=True, help="suite files to run")
    pack.add_argument("--twins", type=Path, required=True, help="twin files to run")
    pack.add_argument("--shard-count", type=int, required=True)
    pack.add_argument("--out", type=Path, required=True)
    pack.add_argument("--ledger", type=Path, default=None, help="per-file test counts")
    check = sub.add_parser("check", help="did every planned shard report its tests?")
    check.add_argument("--plan", type=Path, required=True, help="the plan directory")
    check.add_argument("--results", type=Path, required=True, help="the shards' pytest summaries")
    check.add_argument("--result", action="append", default=[], metavar="POPULATION=FILE")
    check.add_argument("--ledger", type=Path, default=None, help="per-file test counts")
    args = parser.parse_args(argv)
    return cmd_pack(args) if args.cmd == "pack" else cmd_check(args)


if __name__ == "__main__":
    raise SystemExit(main())
