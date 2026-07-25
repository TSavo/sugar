#!/usr/bin/env python3
"""Bounded replay at current head, over candidate sites ONLY.

THE BOUND, AND WHY
==================
Not a second census. The projection exists precisely to avoid paying for a full
re-measurement to remove three already-known deltas, so this replays the
SMALLEST set of files that can confirm or contradict the expected attribution:

    the set of files that contributed at least one `NameErrorEffect`
    occurrence to the pinned census.

Justification, delta by delta:

* #6284 (c11767c5e) is the ONLY one of the three claimed as semantic progress,
  and its claim is exactly "the fabricated NameErrorEffect on bound-then-raise
  is retired". `NameErrorEffect` occurrences are therefore both the target and
  the discriminator: replaying their files at head measures the retirement
  directly. 940 occurrences in the pinned run.
* #6286 is a failure-CARDINALITY correction (repeated binary-resolution fallout
  collapsing to one honest error). Cardinality corrections are visible as a
  change in row multiplicity for the SAME sites, so replaying the same bounded
  file set also exposes it, without needing the whole corpus.
* #6288 re-keys roll-call twin rows. Roll-call rows are a suite artifact, not a
  pandas-corpus artifact -- this census produced none -- so #6288 is expected
  to be a no-op HERE. Replaying the bound confirms that rather than assuming
  it.

Every file outside the bound is reported as NOT REPLAYED. An unreplayed file is
not "unchanged"; it is unmeasured, and the ledger says so.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path


def main() -> int:
    dump = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    target_family = sys.argv[3] if len(sys.argv) > 3 else "NameErrorEffect"

    from sugar_lift_py_tests.desugar_axis import DesugarAxis
    from sugar_lift_py_tests.audit_only.collect_construction_gaps import (
        collect_construction_panic,
    )
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    sys.setrecursionlimit(100000)
    root = Path(dump["root"])

    # Occurrence keys carry `site:<abs-path>:line:col` or `occurrence:<id>`.
    # Resolve the ones that name a real corpus file into the bounded file set.
    pinned_occ = [o.split("\t", 1) for o in dump["desugarOccurrences"]]
    target_occ = {occ for owner, occ in pinned_occ if owner == target_family}

    bound_files: set[str] = set()
    for occ in target_occ:
        if ":" not in occ:
            continue
        body = occ.split(":", 1)[1]
        for part in (body,):
            idx = part.find(str(root))
            if idx >= 0:
                path = part[idx:].rsplit(":", 2)[0]
                try:
                    bound_files.add(str(Path(path).relative_to(root)))
                except ValueError:
                    pass

    print(f"target family    : {target_family}")
    print(f"pinned occurrences: {len(target_occ)}")
    print(f"bounded files     : {len(bound_files)} of {dump['files']}")

    axis = DesugarAxis()
    crashes: Counter = Counter()
    t0 = time.time()
    for i, rel in enumerate(sorted(bound_files)):
        f = root / rel

        def _measure(_f=f, _rel=rel):
            reporter = CollectingReporter()
            sf = SourceFile.from_path(str(_f), reporter=reporter)
            for fn in sf.functions():
                try:
                    span = fn.line_col_span()
                    where = f"{_rel}:{span.start_line}:{span.start_col}"
                except Exception:  # noqa: BLE001
                    where = f"{_rel}:?"
                try:
                    sugar = fn.sugar()
                except SugarNotWritten:
                    sugar = None
                if sugar is not None:
                    axis.measure(sugar, where=where)
            return 0

        try:
            _, panic = collect_construction_panic(rel, _measure)
            if panic is not None:
                crashes["ConstructionPanic"] += 1
        except Exception as e:  # noqa: BLE001
            crashes[type(e).__name__] += 1
        if (i + 1) % 25 == 0:
            print(f"  [{i + 1}/{len(bound_files)}] {time.time() - t0:.0f}s", flush=True)

    replay_occ = {(o, c) for o, c in axis._seen}
    replay_target = {c for o, c in replay_occ if o == target_family}

    # Restrict the pinned comparison to the SAME bounded files, so a shrink is
    # never manufactured by comparing a bounded replay to a full-corpus count.
    def in_bound(occ: str) -> bool:
        return any(bf in occ for bf in bound_files)

    pinned_in_bound = Counter(
        owner for owner, occ in pinned_occ if in_bound(occ)
    )
    replay_in_bound = Counter(owner for owner, occ in replay_occ)

    families = sorted(set(pinned_in_bound) | set(replay_in_bound))
    delta = {
        fam: {
            "pinned": pinned_in_bound.get(fam, 0),
            "replay": replay_in_bound.get(fam, 0),
            "delta": replay_in_bound.get(fam, 0) - pinned_in_bound.get(fam, 0),
        }
        for fam in families
    }

    payload = {
        "pinnedCommit": "d94f67a3149ea2aceee4f9a8cff0397b6f6d374a",
        "replayCommit": "c11767c5e48f2e6799d0d4a0d58823ea84486ac6",
        "targetFamily": target_family,
        "boundFiles": len(bound_files),
        "boundFileList": sorted(bound_files),
        "corpusFiles": dump["files"],
        "notReplayed": dump["files"] - len(bound_files),
        "pinnedTargetOccurrencesCorpusWide": len(target_occ),
        "pinnedTargetOccurrencesInBound": pinned_in_bound.get(target_family, 0),
        "replayTargetOccurrencesInBound": len(replay_target),
        "familyDeltaInBound": delta,
        "replayCrashes": crashes.most_common(),
        "replayDefects": len(axis.defects),
        "replayPanics": len(axis.construction_panics),
        "wallSeconds": round(time.time() - t0, 1),
    }
    out.write_text(json.dumps(payload, indent=2))
    print(json.dumps({k: v for k, v in payload.items()
                      if k not in ("boundFileList", "familyDeltaInBound")}, indent=2))
    print("--- family delta within bound ---")
    for fam, d in sorted(delta.items(), key=lambda kv: -abs(kv[1]["delta"])):
        if d["delta"] or d["pinned"]:
            print(f"{d['pinned']:6d} -> {d['replay']:6d}  ({d['delta']:+d})  {fam}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
