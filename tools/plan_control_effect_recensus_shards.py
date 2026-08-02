#!/usr/bin/env python3
"""Plan LPT file shards for control-effect recensus (banked law R1).

Does not measure. Writes a content-addressed plan JSON that workers and
compose_control_effect_board consume. SCOREBOARD_AUTHORITY = False.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCOREBOARD_AUTHORITY = False

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

_SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "implementations/python/sugar-lift-py-tests/scripts"
)
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lpt_file_shards import (  # noqa: E402
    ContentAddressedCostPrior,
    DEFAULT_SHARD_COUNT,
    assign_files,
)
from compose_control_effect_board import build_plan  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--enrolled-files",
        type=Path,
        required=True,
        help="JSON list of enrolled relative paths (corpus pin order or any)",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        required=True,
        help="filesystem root for content-addressed prior lookups",
    )
    parser.add_argument("--shard-count", type=int, default=DEFAULT_SHARD_COUNT)
    parser.add_argument("--measured-commit", required=True)
    parser.add_argument("--aggregate-hash", required=True)
    parser.add_argument("--manifest-shape-cid", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    enrolled = json.loads(args.enrolled_files.read_text(encoding="utf-8"))
    if not isinstance(enrolled, list) or not all(isinstance(x, str) for x in enrolled):
        parser.error("--enrolled-files must be a JSON list of strings")
    enrolled = sorted(enrolled)
    root = args.corpus_root.resolve()
    path_resolver = {rel: root / rel for rel in enrolled}
    # Also try package-stripped keys (pandas/foo.py vs foo.py).
    for rel in list(enrolled):
        if "/" in rel:
            path_resolver.setdefault(rel.split("/", 1)[1], root / rel.split("/", 1)[1])

    assignment = assign_files(
        enrolled,
        shard_count=args.shard_count,
        path_resolver={rel: path_resolver[rel] for rel in enrolled if rel in path_resolver and path_resolver[rel].is_file()},
        prior=ContentAddressedCostPrior(),
    )
    # If path resolver empty for all, equal-count still works via assign_files.
    plan = build_plan(
        enrolled_files=enrolled,
        shard_count=args.shard_count,
        measured_commit=args.measured_commit,
        aggregate_hash=args.aggregate_hash,
        manifest_shape_cid=args.manifest_shape_cid,
        bins=assignment.bins,
        split_mode=assignment.mode,
        prior_hits=assignment.prior_hits,
        prior_misses=assignment.prior_misses,
        estimated_loads=assignment.estimated_loads,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"PLAN mode={assignment.mode} k={args.shard_count} "
        f"prior_hits={assignment.prior_hits} prior_misses={assignment.prior_misses} "
        f"planCid={plan['planCid']} out={args.out}",
        flush=True,
    )
    print(assignment.job_log_line(population="control-effect-recensus"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
