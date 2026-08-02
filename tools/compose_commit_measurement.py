#!/usr/bin/env python3
"""Compose CommitMeasurement from sealed receipts — S0.3-ready, allow Partial.

S0.3 REQUIRED artifacts (path-forward.md): board JSON + process-floor R triple.
CommitMeasurement is OPTIONAL and MAY BE PARTIAL (package suite may not have
spoken yet). This CLI never uses --require-complete.

    python3 tools/compose_commit_measurement.py \\
      --commit "$SHA" \\
      --receipts-dir receipts/ \\
      --output commit-measurement.json

Exit codes:
  0  composition written (CompleteVector or PartialVector)
  2  usage / IO / constructor failure

Do NOT fire this against in-flight S0.1/S0.2 runs until their artifacts land.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def _load_cm():
    path = Path(__file__).resolve().parent / "commit_measurement.py"
    spec = importlib.util.spec_from_file_location("commit_measurement", path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load tools/commit_measurement.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True, help="tip SHA under composition")
    parser.add_argument(
        "--receipts-dir",
        type=Path,
        required=True,
        help="directory of downloaded lease/body JSON artifacts",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("commit-measurement.json"),
        help="where to write the composition JSON (default: commit-measurement.json)",
    )
    parser.add_argument(
        "--roster-cid",
        default="heavy-roster:per-commit",
        help="roster content id string bound into the vector",
    )
    # Intentionally NO --require-complete. S0.3 packaging allows PartialVector.
    args = parser.parse_args(argv)

    cm = _load_cm()
    try:
        vector = cm.compose_tip_from_receipts_dir(
            args.commit,
            args.receipts_dir,
            roster_cid=args.roster_cid,
        )
    except cm.CommitMeasurementError as exc:
        print(f"compose-commit-measurement REFUSED: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"compose-commit-measurement IO: {exc}", file=sys.stderr)
        return 2

    payload = vector.to_json()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    status = payload.get("status")
    print(f"wrote {args.output} status={status}")
    if status == "partial":
        print(
            "PartialVector (honest): unmeasuredAxes="
            f"{payload.get('unmeasuredAxes')!r} — no total; "
            "criterion-2 Complete requires every enrolled axis including "
            "R_construction_panics (control-effect recensus); four green "
            "process floors alone are Partial"
        )
        # Exit 0: partial is success for this CLI. Use
        # commit_measurement_gate --require-complete only for tip-complete claims.
        return 0
    # CompleteVector has no scalar total across mixed units (locus vs file vs
    # construction-panic). valuesByUnit is a per-unit bag, not a residual sum.
    print(
        f"CompleteVector valuesByUnit={payload.get('valuesByUnit')!r} "
        f"(total={payload.get('total')!r} — always null for multi-unit C2)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
