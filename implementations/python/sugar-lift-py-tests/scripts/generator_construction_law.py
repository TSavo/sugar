#!/usr/bin/env python3
"""R_generator_construction: suspended-machine construction floor."""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.

from sugar_lift_py_tests.repo_root import resolve_repo_root

SCOREBOARD_AUTHORITY = False

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class GeneratorConstructionOffender:
    coordinate: str
    observed: str
    requested: str = "GeneratorConstructionV1 suspended-machine construction"


def scan(repository: Path) -> tuple[int, list[GeneratorConstructionOffender]]:
    roots = {
        "nodes": repository
        / "implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py",
        "frame": repository
        / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/source_call_frame.py",
        "call": repository
        / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/call_site_sugar.py",
        "with": repository
        / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/generator_with_sugar.py",
    }
    text = {name: path.read_text() for name, path in roots.items()}
    checks = (
        (
            "Yield._construct_sugar",
            "class Yield" in text["nodes"] and "YieldSuspensionSugar" in text["nodes"],
            "Yield has no suspended-frame construction step",
        ),
        (
            "FunctionDef.source_visible_call_frame",
            "generator_steps" in text["frame"],
            "source call frame cannot carry constructed generator steps",
        ),
        (
            "CallSiteSugar.source_call_frame",
            "GeneratorConstructionV1" in text["call"],
            "source generator calls still share the eager body-return arm",
        ),
        (
            "GeneratorWithSugar.generator_manager",
            "GeneratorConstructionV1" in text["with"]
            and "contextlib" not in text["with"]
            and "warning" not in text["with"],
            "With has no name-independent generator-machine consumer",
        ),
    )
    offenders = [
        GeneratorConstructionOffender(coordinate, observed)
        for coordinate, satisfied, observed in checks
        if not satisfied
    ]
    return len(checks), offenders


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=resolve_repo_root())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    discovered, offenders = scan(args.repository.resolve())
    summary = {
        "instrument": "R_generator_construction",
        "discovered": discovered,
        "completed": discovered,
        "R_generator_construction": len(offenders),
        "offenders": [asdict(item) for item in offenders],
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            f"R_generator_construction = {len(offenders)} "
            f"(discovered={discovered}, completed={discovered})"
        )
        for offender in offenders:
            print(
                f"- {offender.coordinate}: {offender.observed}; replace with {offender.requested}"
            )
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
