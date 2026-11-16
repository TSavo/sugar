#!/usr/bin/env python3
"""Pack the scorecard's test files to run onto its shards by measured cost.

WHY THIS EXISTS (#8416)

The main scorecard's suite shards each re-derived their files from the whole
suite roster, and the LPT cost prior they consulted lived in the job's
workspace, which every checkout wiped: every run fell back to equal counts
(68 files a shard) and the shards' walls ranged from 2 to 17 minutes. The
solver twins were a separate 20-minute job that re-ran 50 files the suite
shards had already run.

The plan job now runs this once. It takes the files the carry plan says must
run -- the suite's, and the twin files outside the suite tree (the twins in
the suite tree are read from the suite's own results) -- and packs them onto
the shards with tools/lpt_file_shards.py on the shared prior
(SUGAR_LPT_PRIOR_DIR, written by tools/scorecard_carry_pytest.py after every
pytest with each file's measured wall seconds). Files with no prior yet are
estimated from their size, as lpt_file_shards does.

Writes, for each shard i, ``<out>/shard-<ii>.suite.txt`` and
``<out>/shard-<ii>.twins.txt`` (paths relative to implementations/python,
one per line; either may be empty).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from lpt_file_shards import ContentAddressedCostPrior, assign_files, narrate_assignment


def read_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cwd", type=Path, required=True, help="implementations/python")
    parser.add_argument("--suite", type=Path, required=True, help="suite files to run")
    parser.add_argument("--twins", type=Path, required=True, help="twin files to run")
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

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

    args.out.mkdir(parents=True, exist_ok=True)
    for index, bucket in enumerate(assignment.bins):
        by_population: dict[str, list[str]] = {"suite": [], "twins": []}
        for key in bucket:
            population, rel = key.split("\t", 1)
            by_population[population].append(rel)
        for population, rels in by_population.items():
            (args.out / f"shard-{index:02d}.{population}.txt").write_text(
                "".join(f"{rel}\n" for rel in sorted(rels)), encoding="utf-8"
            )
        load = assignment.estimated_loads[index] if assignment.estimated_loads else 0.0
        print(
            f"SCORECARD SHARD PLAN shard={index} suite_files={len(by_population['suite'])} "
            f"twins_files={len(by_population['twins'])} estimated_s={load:.1f} "
            f"mode={assignment.mode}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
