#!/usr/bin/env python3
"""Rank the 1074 desugar construction panics by OWNER MECHANISM.

THE QUESTION THIS ANSWERS, AND WHY IT OUTRANKS EVERYTHING ELSE
==============================================================
A ConstructionPanic during desugar is a construction-law None arm firing. The
census reports 1074 of them and prints only the first 40, so the deciding fact
has never been visible: are these

  (a) 1074 GENUINE product panics -- stop-the-line under the Python DoD, and
      they outrank With entirely; or
  (b) a SMALL number of known, typed owner mechanisms amplified across many
      occurrences -- in which case the dispatchable quantity is the MECHANISM
      COUNT, not the occurrence count.

Occurrence count is what a naive read reports and it is the wrong unit: 1074
occurrences of three mechanisms is three pieces of work, not 1074.

This tallies mechanism -> occurrences, mechanism -> distinct message shape,
and mechanism -> file spread, so the answer is read rather than assumed.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def normalise(msg: str) -> str:
    """Collapse a panic message to its SHAPE, so occurrences of one mechanism
    do not look like distinct mechanisms merely because they name different
    files, lines, or identifiers."""
    if not msg:
        return "<no message>"
    m = msg.strip().splitlines()[0]
    m = re.sub(r"/[^\s:]+\.py:\d+:\d+", "<site>", m)
    m = re.sub(r"\b\d+\b", "<n>", m)
    m = re.sub(r"'[^']*'", "'<id>'", m)
    m = re.sub(r"\s+", " ", m)
    return m[:200]


def main() -> int:
    dump = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    panics = dump["desugarConstructionPanics"]

    by_owner: Counter = Counter()
    shapes_by_owner: dict[str, Counter] = defaultdict(Counter)
    files_by_owner: dict[str, set] = defaultdict(set)
    for p in panics:
        owner = p.get("owner") or "<no owner>"
        by_owner[owner] += 1
        shapes_by_owner[owner][normalise(p.get("message") or "")] += 1
        files_by_owner[owner].add((p.get("where") or "?").rsplit(":", 2)[0])

    all_shapes = Counter()
    for owner, shapes in shapes_by_owner.items():
        for shape, n in shapes.items():
            all_shapes[f"{owner} :: {shape}"] += n

    mechanisms = [
        {
            "owner": owner,
            "occurrences": n,
            "distinctMessageShapes": len(shapes_by_owner[owner]),
            "filesAffected": len(files_by_owner[owner]),
            "shapes": shapes_by_owner[owner].most_common(5),
        }
        for owner, n in by_owner.most_common()
    ]

    payload = {
        "totalPanicOccurrences": len(panics),
        "distinctOwnerMechanisms": len(by_owner),
        "distinctOwnerMessageShapePairs": len(all_shapes),
        "mechanisms": mechanisms,
        "verdict": (
            "amplified-known-mechanisms"
            if len(by_owner) <= 12
            else "many-distinct-mechanisms"
        ),
    }
    out.write_text(json.dumps(payload, indent=2))

    print(f"total panic OCCURRENCES     : {payload['totalPanicOccurrences']}")
    print(f"distinct owner MECHANISMS   : {payload['distinctOwnerMechanisms']}")
    print(f"distinct owner+shape pairs  : {payload['distinctOwnerMessageShapePairs']}")
    print(f"verdict                     : {payload['verdict']}")
    print()
    print(f"{'occurrences':>11}  {'shapes':>6}  {'files':>5}  owner mechanism")
    for m in mechanisms:
        print(
            f"{m['occurrences']:>11}  {m['distinctMessageShapes']:>6}  "
            f"{m['filesAffected']:>5}  {m['owner']}"
        )
    print()
    print("--- message shape per mechanism ---")
    for m in mechanisms:
        print(f"\n[{m['owner']}]  {m['occurrences']} occurrences")
        for shape, n in m["shapes"]:
            print(f"   {n:6d}  {shape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
