#!/usr/bin/env python3
"""Coretests hermetic sweep → live R vector (no equality pin).

KILLS the authored-state pin (coretests-invariants.json). Counts are MEASURED
output from the hermetic sweep under a declared scope, never seeded from a
hand-edited file. Transcribing pin constants into a "Measured" vector would be
the pin wearing a Measured coat — forbidden.

AXIS SPLIT
----------
FLOORS (must be zero; hard red; true must-never-happen):
  R_silent, R_unclassified, R_panicked_files, R_missing_assertions
  plus: accounting identity must close (parts sum to whole or something vanished)

RESIDUAL (R>0 is red until stable zero — drain pressure, never green-at-N):
  R_refused, R_inactive

DERIVED CONTEXT (reported, not asserted equal to anything):
  discharged, callsite_expansion

DRIFT MEMBRANE (not a residual pin):
  assertion_multiset_cid — content-addressed surface identity. Recorded on every
  Measured body. Compared only to a PRIOR banked measurement receipt when one
  is supplied (never to constants in a human-edited file).

UNMEASURED
----------
If the sweep crashes, exits non-zero before a complete headline, or omits a
required line, this program exits UNMEASURED — never invents a count. Same law
as process-floor #7004: silence is not zero.

Usage:
  # Measure from complete hermetic stdout (exit 0 only if floors zero AND residual zero)
  python3 scripts/check-coretests-invariants.py \\
      --sweep-stdout /tmp/coretests-hermetic.out \\
      --body-out coretests-measurement.json \\
      --require-commit "$GITHUB_SHA"

  # Optional regression membrane vs a prior banked Measured body
  python3 scripts/check-coretests-invariants.py ... \\
      --previous-body prior/coretests-measurement.json

Exit:
  0  Measured, all floors zero, all residual zero, accounting closed
  1  Measured but floors violated and/or residual R>0 (drain / floor red)
  2  UNMEASURED (incomplete or unreadable sweep)
  3  usage / identity binding failure
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


# Floors: R must be 0 or hard red.
FLOOR_AXES = (
    "R_silent",
    "R_unclassified",
    "R_panicked_files",
    "R_missing_assertions",
)

# Residual: R>0 is red until stable zero (drain pressure).
RESIDUAL_AXES = (
    "R_refused",
    "R_inactive",
)


def parse_headline(text: str) -> dict[str, Any]:
    """Parse hermetic sweep stdout. Missing required fields → incomplete."""

    def grab(pattern: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1) if m else None

    def i(s: str | None) -> int | None:
        return int(s) if s is not None else None

    accounting = grab(
        r"accounting identity:\s*(-?\d+)\s+raw surfaces\s+\+\s*(-?\d+)\s+expanded\s+-\s*(-?\d+)\s+missing\s+=\s*(-?\d+)\s+accounted"
    )
    raw = exp = miss = accounted = None
    if accounting:
        # re-search with groups
        m = re.search(
            r"accounting identity:\s*(-?\d+)\s+raw surfaces\s+\+\s*(-?\d+)\s+expanded\s+-\s*(-?\d+)\s+missing\s+=\s*(-?\d+)\s+accounted",
            text,
        )
        if m:
            raw, exp, miss, accounted = (int(m.group(j)) for j in range(1, 5))

    return {
        "discharged": i(grab(r"discharged \(lifted to FOL\):\s*(-?\d+)")),
        "refused": i(grab(r"refused\s+\(TERMINAL[^:]*:\s*(-?\d+)")),
        "unclassified": i(grab(r"unclassified \(lifter[^:]*:\s*(-?\d+)")),
        "inactive": i(grab(r"inactive \(cfg-disabled\):\s*(-?\d+)")),
        "panicked_files": i(grab(r"panicked files \(LIFTER GAP\):\s*(-?\d+)")),
        "silent": i(grab(r"missing assertions \(SILENT\):\s*(-?\d+)")),
        "missing_assertions": i(grab(r"missing assertions \(SILENT\):\s*(-?\d+)")),
        "callsite_expansion": i(grab(r"callsite-expanded obligations:\s*(-?\d+)")),
        "assertion_multiset_cid": grab(
            r"assertion multiset cid:\s*(blake3-512:[0-9a-f]+)"
        ),
        "accounting_raw": raw,
        "accounting_expanded": exp,
        "accounting_missing": miss,
        "accounting_accounted": accounted,
        "corpus_line": grab(r"^corpus:\s*(.+)$"),
    }


REQUIRED_FOR_MEASURED = (
    "discharged",
    "refused",
    "unclassified",
    "inactive",
    "panicked_files",
    "silent",
    "missing_assertions",
    "callsite_expansion",
    "assertion_multiset_cid",
    "accounting_raw",
    "accounting_expanded",
    "accounting_missing",
    "accounting_accounted",
)


def incompleteness(got: dict[str, Any]) -> list[str]:
    reasons = []
    for key in REQUIRED_FOR_MEASURED:
        if got.get(key) is None:
            reasons.append(f"missing headline field {key!r}")
    # Sweep binaries that predate panicked_files cannot prove a reading.
    if got.get("panicked_files") is None:
        reasons.append(
            "no `panicked files (LIFTER GAP)` line — incomplete sweep / old binary"
        )
    return reasons


def accounting_identity_closes(got: dict[str, Any]) -> bool:
    """raw + expanded - missing == accounted, and accounted == sum of disposition buckets."""
    raw = got["accounting_raw"]
    exp = got["accounting_expanded"]
    miss = got["accounting_missing"]
    accounted = got["accounting_accounted"]
    if raw + exp - miss != accounted:
        return False
    # Disposition partition of accounted obligations.
    buckets = (
        got["discharged"]
        + got["refused"]
        + got["unclassified"]
        + got["inactive"]
    )
    return buckets == accounted


def body_cid(body: dict[str, Any]) -> str:
    """Content-address the measurement body (excluding bodyCid itself)."""
    payload = {k: v for k, v in body.items() if k != "bodyCid"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    digest = hashlib.sha256(canonical).hexdigest()
    return f"sha256:{digest}"


def build_measured_body(
    got: dict[str, Any],
    *,
    commit: str | None,
    scope: dict[str, Any],
) -> dict[str, Any]:
    floors = {
        "R_silent": got["silent"],
        "R_unclassified": got["unclassified"],
        "R_panicked_files": got["panicked_files"],
        "R_missing_assertions": got["missing_assertions"],
        "accounting_identity_closed": accounting_identity_closes(got),
    }
    residual = {
        "R_refused": got["refused"],
        "R_inactive": got["inactive"],
    }
    context = {
        "discharged": got["discharged"],
        "callsite_expansion": got["callsite_expansion"],
        "accounting": {
            "raw_surfaces": got["accounting_raw"],
            "expanded": got["accounting_expanded"],
            "missing": got["accounting_missing"],
            "accounted": got["accounting_accounted"],
        },
    }
    body: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "coretests-hermetic-measurement",
        "status": "Measured",
        "unmeasuredReason": None,
        "measuredCommit": commit,
        "scope": scope,
        "floors": floors,
        "residual": residual,
        "context": context,
        "assertion_multiset_cid": got["assertion_multiset_cid"],
    }
    body["bodyCid"] = body_cid(body)
    return body


def build_unmeasured_body(
    reason: str,
    *,
    commit: str | None,
    scope: dict[str, Any],
) -> dict[str, Any]:
    # Explicit UNMEASURED: no residual/floor numbers. A pinned zero is not a
    # measured zero; a transcribed residual constant is the pin wearing a
    # Measured coat.
    body: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "coretests-hermetic-measurement",
        "status": "Unmeasured",
        "unmeasuredReason": reason,
        "measuredCommit": commit,
        "scope": scope,
        "floors": {axis: None for axis in FLOOR_AXES}
        | {"accounting_identity_closed": None},
        "residual": {axis: None for axis in RESIDUAL_AXES},
        "context": {"discharged": None, "callsite_expansion": None},
        "assertion_multiset_cid": None,
    }
    body["bodyCid"] = body_cid(body)
    return body


def evaluate_measured(body: dict[str, Any]) -> list[str]:
    """Return red reasons (empty ⇒ green). Never compares to an authored pin."""
    red: list[str] = []
    floors = body["floors"]
    for axis in FLOOR_AXES:
        value = floors.get(axis)
        if value is None:
            red.append(f"floor {axis} is UNMEASURED inside a Measured body")
        elif value != 0:
            red.append(f"floor {axis}={value} (must be 0)")
    if floors.get("accounting_identity_closed") is not True:
        red.append(
            "floor accounting_identity_closed=false "
            "(parts do not sum to whole — vanished rows)"
        )
    residual = body["residual"]
    for axis in RESIDUAL_AXES:
        value = residual.get(axis)
        if value is None:
            red.append(f"residual {axis} is UNMEASURED inside a Measured body")
        elif value > 0:
            red.append(
                f"residual {axis}={value} (R>0; drain pressure — never green-at-N)"
            )
    return red


def regression_vs_previous(
    body: dict[str, Any], previous: dict[str, Any]
) -> list[str]:
    """Compare to a prior banked Measured receipt — never to file constants."""
    red: list[str] = []
    if previous.get("status") != "Measured":
        return red  # no measured baseline; cannot claim residual regression
    prev_res = previous.get("residual") or {}
    cur_res = body.get("residual") or {}
    for axis in RESIDUAL_AXES:
        prev_v, cur_v = prev_res.get(axis), cur_res.get(axis)
        if isinstance(prev_v, int) and isinstance(cur_v, int) and cur_v > prev_v:
            red.append(
                f"regression {axis}: {prev_v} → {cur_v} "
                f"(vs prior Measured bodyCid={previous.get('bodyCid')})"
            )
    prev_cid = previous.get("assertion_multiset_cid")
    cur_cid = body.get("assertion_multiset_cid")
    if prev_cid and cur_cid and prev_cid != cur_cid:
        # Drift membrane: surface identity changed. Not a residual pin.
        # Residual regression is already covered above; CID-only change with
        # free residual improvement is still a surface change that must be loud.
        red.append(
            f"assertion_multiset_cid drift membrane: "
            f"{prev_cid} → {cur_cid} (corpus or semantic surface changed; "
            f"not a secret re-pin of residual counts)"
        )
    return red


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sweep-stdout",
        type=Path,
        required=True,
        help="path to hermetic coretests_sweep stdout (complete or not)",
    )
    parser.add_argument(
        "--body-out",
        type=Path,
        required=True,
        help="write content-addressed measurement body JSON here",
    )
    parser.add_argument(
        "--require-commit",
        default=None,
        help="measuredCommit binding (usually GITHUB_SHA)",
    )
    parser.add_argument(
        "--toolchain",
        default=None,
        help="declared rustc toolchain for scope (e.g. 1.96.0)",
    )
    parser.add_argument(
        "--corpus",
        default=None,
        help="declared corpus path for scope",
    )
    parser.add_argument(
        "--previous-body",
        type=Path,
        default=None,
        help="optional prior banked Measured body for residual/CID membrane",
    )
    parser.add_argument(
        "--sweep-exit",
        type=int,
        default=0,
        help="exit code of the sweep process (nonzero ⇒ UNMEASURED)",
    )
    args = parser.parse_args(argv)

    scope = {
        "mode": "hermetic",
        "toolchain": args.toolchain,
        "corpus": args.corpus,
        "note": (
            "Counts are re-derived by coretests_sweep under this scope. "
            "They are never seeded from a deleted pin file."
        ),
    }

    if args.sweep_exit != 0:
        body = build_unmeasured_body(
            f"sweep process exit {args.sweep_exit} before a complete reading",
            commit=args.require_commit,
            scope=scope,
        )
        args.body_out.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        print(
            f"coretests: UNMEASURED — sweep exit {args.sweep_exit}",
            file=sys.stderr,
        )
        print(f"body: {args.body_out} status=Unmeasured")
        return 2

    try:
        text = args.sweep_stdout.read_text(encoding="utf-8")
    except OSError as exc:
        body = build_unmeasured_body(
            f"sweep stdout unreadable: {exc}",
            commit=args.require_commit,
            scope=scope,
        )
        args.body_out.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        print(f"coretests: UNMEASURED — {exc}", file=sys.stderr)
        return 2

    got = parse_headline(text)
    gaps = incompleteness(got)
    if gaps:
        body = build_unmeasured_body(
            "incomplete hermetic headline: " + "; ".join(gaps),
            commit=args.require_commit,
            scope=scope,
        )
        args.body_out.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        print("coretests: UNMEASURED — incomplete sweep headline", file=sys.stderr)
        for g in gaps:
            print(f"  - {g}", file=sys.stderr)
        print(f"body: {args.body_out} status=Unmeasured")
        return 2

    body = build_measured_body(got, commit=args.require_commit, scope=scope)
    red = evaluate_measured(body)

    if args.previous_body is not None and args.previous_body.is_file():
        try:
            previous = json.loads(args.previous_body.read_text(encoding="utf-8"))
            red.extend(regression_vs_previous(body, previous))
        except (OSError, ValueError) as exc:
            red.append(f"previous-body unreadable: {exc}")

    args.body_out.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")

    print("### coretests hermetic measurement")
    print()
    print(f"- status: `{body['status']}`")
    print(f"- bodyCid: `{body['bodyCid']}`")
    print(f"- assertion_multiset_cid: `{body['assertion_multiset_cid']}`")
    print(f"- floors: `{json.dumps(body['floors'], sort_keys=True)}`")
    print(f"- residual: `{json.dumps(body['residual'], sort_keys=True)}`")
    print(f"- context (not asserted): `{json.dumps(body['context'], sort_keys=True)}`")
    print()
    if red:
        print("**RED** — floors violated and/or residual R>0 (or membrane):")
        for line in red:
            print(f"- {line}")
            print(f"::error::{line}", file=sys.stderr)
        return 1

    print(
        "**GREEN** — floors zero, residual zero, accounting closed "
        "(no equality pin; numbers re-derived this run)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
