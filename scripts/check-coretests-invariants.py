#!/usr/bin/env python3
"""CI gate for the rust stdlib coretests accounting sweep.

Runs against the HERMETIC sweep (no `--dissolve`): that pass is fully
deterministic (no nightly harness compiles, no per-file dissolution cap), so its
numbers are exact and reproducible -- a stable CI gate.

THE CONTRACT: each push pins the EXPECTED snapshot it should produce. CI runs the
sweep and asserts the result EQUALS the pin, EXACTLY. CI goes red precisely when
the numbers do not move the way the commit claimed -- a drain that didn't drain, a
regression, a silent drop, or a corpus change. To land a change you must predict
its effect and pin it; reality is checked against your claim.

Usage:
    check-coretests-invariants.py <sweep-stdout-file> <pinned-invariants.json>

Pinned JSON shape (all fields exact-matched):
    {
      "assertion_multiset_cid": "blake3-512:...",  # the corpus universe
      "silent": 0,                                  # missing assertions (HARD: 0)
      "missing_assertions": 0,                      # source assertions not reached
      "callsite_expansion": 52,                     # extra obligations from source digs
      "discharged": 5882,                           # lifted to FOL (hermetic)
      "refused": 291,                               # terminal, with reason
      "unclassified": 196,                          # the roadmap; drive to 0
      "prev_unclassified": 207,                     # last push, for a direction check
      "note": "free-text: what this commit moved and why"
    }

Exit 0 iff the sweep equals the pin exactly (and unclassified did not regress vs
prev_unclassified); nonzero with a diff otherwise.
"""
import json
import re
import sys


def parse_headline(text: str) -> dict:
    def grab(pattern):
        m = re.search(pattern, text)
        return m.group(1) if m else None

    def i(s):
        return int(s) if s is not None else None

    return {
        "discharged": i(grab(r"discharged \(lifted to FOL\):\s*(-?\d+)")),
        "refused": i(grab(r"refused\s+\(TERMINAL[^:]*:\s*(-?\d+)")),
        "unclassified": i(grab(r"unclassified \(lifter[^:]*:\s*(-?\d+)")),
        "silent": i(grab(r"missing assertions \(SILENT\):\s*(-?\d+)")),
        "missing_assertions": i(grab(r"missing assertions \(SILENT\):\s*(-?\d+)")),
        "callsite_expansion": i(grab(r"callsite-expanded obligations:\s*(-?\d+)")),
        "cid": grab(r"assertion multiset cid:\s*(blake3-512:[0-9a-f]+)"),
    }


# Each exact-matched field: (sweep_key, pin_key, why-it-matters-on-mismatch).
EXACT = [
    ("cid", "assertion_multiset_cid",
     "corpus assertion universe changed (rust version bump?); re-pin deliberately"),
    ("silent", "silent",
     "an assertion was SILENTLY dropped -- unsound; this must stay 0"),
    ("missing_assertions", "missing_assertions",
     "source assertion accounting has a missing site"),
    ("callsite_expansion", "callsite_expansion",
     "source callsite expansion count shifted"),
    ("discharged", "discharged",
     "lifted-to-FOL count is not what the commit claimed"),
    ("refused", "refused",
     "terminal-refused count is not what the commit claimed"),
    ("unclassified", "unclassified",
     "unclassified is not what the commit claimed it would move to"),
]


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    got = parse_headline(open(sys.argv[1], encoding="utf-8").read())
    pin = json.load(open(sys.argv[2], encoding="utf-8"))

    failures = []
    for sweep_key, pin_key, why in EXACT:
        if pin_key not in pin:
            continue
        if got.get(sweep_key) != pin[pin_key]:
            failures.append(
                f"{sweep_key}: got {got.get(sweep_key)!r}, pinned {pin[pin_key]!r} -- {why}"
            )
    # Direction guard: unclassified must never regress vs the last push.
    if "prev_unclassified" in pin and got.get("unclassified") is not None:
        if got["unclassified"] > pin["prev_unclassified"]:
            failures.append(
                f"unclassified {got['unclassified']} > last push {pin['prev_unclassified']} "
                "-- a regression; we only move toward 0"
            )

    if failures:
        print("coretests invariants: FAIL (the commit did not move as pinned)")
        for f in failures:
            print(f"  - {f}")
        print(f"\n  parsed: {got}")
        print(f"  pinned: { {k: v for k, v in pin.items() if k != 'note'} }")
        return 1

    moved = ""
    if "prev_unclassified" in pin:
        d = pin["prev_unclassified"] - got["unclassified"]
        moved = f", moved {d:+d} vs last push" if d else ", held"
    print(
        f"coretests invariants: OK  (unclassified={got['unclassified']}, "
        f"refused={got['refused']}, discharged={got['discharged']}, SILENT={got['silent']}, "
        f"missing={got['missing_assertions']}, expanded={got['callsite_expansion']}, "
        f"CID pinned{moved})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
