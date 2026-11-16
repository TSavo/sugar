#!/usr/bin/env python3
"""Pack the scorecard's test files onto its shards, and check every shard reported.

    main_scorecard_shard_plan.py pack  --cwd PY --suite F --twins F [--tree F] [--source F] --bin-seconds S --out PLAN
    main_scorecard_shard_plan.py check --plan PLAN --results DIR --result suite=F --result twins=F [--result tree=F] [--result source=F]

A SHARD IS A BIN ON A SHARED QUEUE (#8416, run 43946664351: wall 1919s)

The fast lane has three runners. Eight fixed shards of about 420s each ran
in three waves behind the rust and federation jobs, one single-threaded
pytest at a time on a 32-thread host, and whatever went wrong on one shard
(a fault-signal rerun of its whole suite pytest: +320s on shard 5; a 208s
wait for the release binary federation was building: shard 2) went straight
onto that runner's tail. The plan now cuts the files into many small
population-pure bins (``--bin-seconds`` of measured cost each, so each bin
is ONE pytest under its population's config), numbered longest first; the
workers (main_scorecard_suite.sh run) each run several lanes that claim the
next unclaimed bin until none is left. The longest bins start first, a slow
bin delays only its lane, and the runners finish within about one bin of
each other. ``check`` is unchanged: every bin is a "shard" of shards.json
and must leave its results.

A bin is estimated from, in order: the content-addressed prior (this exact
file's last measured seconds), the path-keyed seconds in the ledger (the
file's last measured seconds before an edit changed its content: an edited
twin used to fall back to a size guess several times too small), then the
file's size. Measured seconds include the file's collection (its import and
module-level work), not only its tests' setup, call and teardown.

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

The ``tree`` population is implementations/python/sugar-source-tree/tests,
which ran in no CI job before: its files are packed onto the same shards by
the same prior (no serial job) and posted as their own ``tree`` number, so
the suite's number keeps counting what it always counted. The ``source``
population is implementations/python/sugar-lift-python-source/tests, which
likewise ran in no CI job (only ``make test-python``): packed and posted the
same way, as its own ``source`` number.

Writes, for each shard (bin) i of population P, ``<out>/shard-<ii>.<P>.txt``
(paths relative to implementations/python, one per line), ``<out>/queue.txt``
(the bin indices in the order lanes claim them: longest estimate first), and
``<out>/shards.json``: how many shards the plan made and, per shard and
population, how many files and about how many tests it was planned to run
(from the ledger of each file's last measured test count).

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
shard makes the twins unmeasured too (and a lost tree or source shard does,
when a twin lives in that package: ``<plan>/twins-in-tree.txt``,
``<plan>/twins-in-source.txt``). A population whose
every shard reported updates the ledger.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

POPULATIONS = ("suite", "twins", "tree", "source")
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


def is_seconds(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def estimate_costs(
    keys: list[str], resolver: dict[str, Path], ledger_seconds: dict
) -> tuple[dict[str, float], dict[str, int]]:
    """Each key's estimated wall seconds, and how many estimates came from each source.

    The content-addressed prior first (this exact file was measured), then the
    path-keyed ledger (this path was measured before its content changed),
    then the size estimate lpt_file_shards calibrates from the measured files.
    """
    from lpt_file_shards import (
        ContentAddressedCostPrior,
        calibrate_size_cost_bins,
        estimate_cost_from_size,
        safe_unknown_cost_floor,
    )

    existing = {key: path for key, path in resolver.items() if path.is_file()}
    prior = ContentAddressedCostPrior()
    costs: dict[str, float] = {}
    if prior.enabled:
        costs, _hits, _misses = prior.costs_for_paths(existing)
    sources = {"prior": len(costs), "ledger": 0, "size": 0}
    for key in keys:
        if key not in costs and is_seconds(ledger_seconds.get(key)):
            costs[key] = float(ledger_seconds[key])
            sources["ledger"] += 1
    floor_s = safe_unknown_cost_floor(list(costs.values()))
    size_pairs: list[tuple[int, float]] = []
    for key, cost in costs.items():
        path = existing.get(key)
        if path is None:
            continue
        try:
            size_pairs.append((path.stat().st_size, float(cost)))
        except OSError:
            continue
    size_bins = calibrate_size_cost_bins(size_pairs)
    for key in keys:
        if key in costs:
            continue
        path = existing.get(key)
        try:
            size = path.stat().st_size if path is not None else None
        except OSError:
            size = None
        costs[key] = (
            floor_s if size is None else estimate_cost_from_size(size, size_bins, floor_s=floor_s)
        )
        sources["size"] += 1
    return costs, sources


def cmd_pack(args: argparse.Namespace) -> int:
    from lpt_file_shards import lpt_bins

    if args.bin_seconds <= 0:
        sys.exit("::error::--bin-seconds must be positive")
    keys: list[str] = []
    resolver: dict[str, Path] = {}
    listings = (
        ("suite", args.suite),
        ("twins", args.twins),
        ("tree", args.tree),
        ("source", args.source),
    )
    for population, listing in listings:
        if listing is None:
            continue
        for rel in read_lines(listing):
            key = f"{population}\t{rel}"
            if key in resolver:
                continue
            keys.append(key)
            resolver[key] = (args.cwd / rel).resolve()

    ledger_doc = (read_json(args.ledger) or {}) if args.ledger else {}
    ledger_counts = ledger_doc.get("files") if isinstance(ledger_doc.get("files"), dict) else {}
    ledger_seconds = ledger_doc.get("seconds") if isinstance(ledger_doc.get("seconds"), dict) else {}
    costs, sources = estimate_costs(keys, resolver, ledger_seconds)

    # Population-pure bins: each bin is one pytest under its population's
    # config. A population gets as many bins as its measured cost needs
    # (ceil(cost / bin seconds)), packed longest-first; one file costlier
    # than a bin is a bin of its own.
    bins: list[tuple[str, list[str], float]] = []
    for population in POPULATIONS:
        members = [key for key in keys if key.split("\t", 1)[0] == population]
        if not members:
            continue
        total = sum(costs[key] for key in members)
        count = max(1, min(len(members), math.ceil(total / args.bin_seconds)))
        for bucket in lpt_bins(members, costs, count, missing_cost=0.0):
            if bucket:
                bins.append((population, sorted(bucket), sum(costs[key] for key in bucket)))
    # Bin 0 is the longest: the queue is claimed in index order, so the long
    # poles start first and the short bins fill the tail.
    bins.sort(key=lambda b: (-b[2], b[0], b[1][0]))

    args.out.mkdir(parents=True, exist_ok=True)
    shards = []
    for index, (population, bucket, estimate) in enumerate(bins):
        rels = [key.split("\t", 1)[1] for key in bucket]
        (args.out / f"shard-{index:02d}.{population}.txt").write_text(
            "".join(f"{rel}\n" for rel in rels), encoding="utf-8"
        )
        counts = [ledger_counts.get(key) for key in bucket]
        planned = sum(n for n in counts if isinstance(n, int))
        shards.append(
            {
                "index": index,
                "population": population,
                "estimatedSeconds": round(estimate, 1),
                population: {
                    "files": len(rels),
                    "testsPlanned": planned,
                    "filesWithoutCount": sum(1 for n in counts if not isinstance(n, int)),
                },
            }
        )
        print(
            f"SCORECARD SHARD PLAN shard={index} population={population} files={len(rels)} "
            f"tests_planned~{planned} estimated_s={estimate:.1f}",
            flush=True,
        )
    (args.out / "queue.txt").write_text(
        "".join(f"{index}\n" for index in range(len(bins))), encoding="utf-8"
    )
    totals = {
        population: sum(b[2] for b in bins if b[0] == population) for population in POPULATIONS
    }
    print(
        f"SCORECARD SHARD PLAN bins={len(bins)} bin_seconds={args.bin_seconds:g} "
        f"estimated_s_total={sum(totals.values()):.1f} "
        + " ".join(f"{population}_s={seconds:.1f}" for population, seconds in totals.items())
        + f" estimates: prior={sources['prior']} ledger={sources['ledger']} size={sources['size']}",
        flush=True,
    )
    write_json(
        args.out / "shards.json",
        {
            "schema": PLAN_SCHEMA,
            "shardCount": len(bins),
            "binSeconds": args.bin_seconds,
            "shards": shards,
        },
    )
    return 0


def shard_loss(results: Path, population: str, index: int, planned: dict) -> str | None:
    """Why shard ``index`` did not measure ``population``, or None when it did."""
    tag = f"{index:02d}"
    exit_file = results / population / f"shard-{tag}.exit"
    try:
        exit_text = exit_file.read_text(encoding="utf-8").strip()
    except OSError:
        exit_text = ""
    if exit_text == "124":
        return "ran past its wall budget (interrupted by timeout, exit 124)"
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
    if lost["tree"] and read_lines(args.plan / "twins-in-tree.txt"):
        lost["twins"].append("tree shards lost (the twins in the source tree are counted from them)")
    if lost["source"] and read_lines(args.plan / "twins-in-source.txt"):
        lost["twins"].append(
            "source shards lost (the twins in sugar-lift-python-source are counted from them)"
        )

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
    """Each run test file's test count, from the shards of complete populations,
    and each run test file's measured seconds (``fileSeconds`` of every summary
    left, complete population or not: a file's seconds are its own), keyed by
    path so an edited file is still estimated by what it cost last time."""
    ledger = read_json(ledger_path) or {}
    files = ledger.get("files") if isinstance(ledger.get("files"), dict) else {}
    seconds = ledger.get("seconds") if isinstance(ledger.get("seconds"), dict) else {}
    measured = 0
    for population in POPULATIONS:
        for summary_path in sorted((results / population).glob("shard-*.json")):
            summary = read_json(summary_path) or {}
            file_seconds = summary.get("fileSeconds")
            if not isinstance(file_seconds, dict):
                continue
            for rel, value in file_seconds.items():
                if isinstance(rel, str) and is_seconds(value):
                    seconds[f"{population}\t{rel}"] = round(float(value), 3)
                    measured += 1
    if not populations and not measured:
        return
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
        write_json(
            ledger_path,
            {"schema": "sugar-main-scorecard-test-counts/v1", "files": files, "seconds": seconds},
        )
    except OSError as exc:
        print(f"::warning::could not write the test-count ledger {ledger_path}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    pack = sub.add_parser("pack", help="pack the files to run onto the shards")
    pack.add_argument("--cwd", type=Path, required=True, help="implementations/python")
    pack.add_argument("--suite", type=Path, required=True, help="suite files to run")
    pack.add_argument("--twins", type=Path, required=True, help="twin files to run")
    pack.add_argument("--tree", type=Path, default=None, help="source-tree test files to run")
    pack.add_argument(
        "--source", type=Path, default=None, help="sugar-lift-python-source test files to run"
    )
    pack.add_argument(
        "--bin-seconds",
        type=float,
        required=True,
        help="target measured seconds per bin (each bin is one pytest a lane claims)",
    )
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
