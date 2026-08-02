#!/usr/bin/env python3
"""GitHub API rate-budget gate — same shape as the load gate for measurements.

A gh call that cannot testify to the budget it is spending is the same defect
class as a measurement that cannot testify to its conditions. The 2026-08-02
infrastructure collapse: eight agents + the runner autoscaler shared one user
token; agents drained core remaining to 0; the autoscaler got 403 on every
runners query, went blind, and 421 jobs queued behind 25 static runners.

Exit codes:
  0   — budget above floor; prints remaining/reset (and runs -- wrap if given)
  79  — remaining below floor; refuse to spend (crime=github-api-budget-low)
  2   — cannot measure budget (gh missing / unauthenticated / network)

Usage:
  python3 tools/gh_rate_budget.py                  # report + exit 0/79
  python3 tools/gh_rate_budget.py --floor 500
  python3 tools/gh_rate_budget.py --json
  python3 tools/gh_rate_budget.py -- wrap -- gh pr view 1 --json url

Env:
  GH_RATE_BUDGET_FLOOR   default floor (default 500 remaining core units)
  GH_TOKEN / gh auth     whatever gh uses; do not point agent gh at the
                         autoscaler vault field — separate identity hub
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any

EXIT_BUDGET = 79
EXIT_MEASURE = 2
DEFAULT_FLOOR = 500


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def fetch_rate_limit() -> dict[str, Any]:
    if shutil.which("gh") is None:
        raise RuntimeError("gh not on PATH")
    # Single lightweight call — this is the budget probe itself.
    proc = subprocess.run(
        ["gh", "api", "rate_limit"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"gh api rate_limit failed: {err[:500]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gh api rate_limit returned non-JSON") from exc


def core_resources(payload: dict[str, Any]) -> dict[str, Any]:
    resources = payload.get("resources") or {}
    core = resources.get("core") or payload.get("rate") or {}
    if not isinstance(core, dict):
        raise RuntimeError("rate_limit payload missing resources.core")
    return core


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--floor",
        type=int,
        default=int(os.environ.get("GH_RATE_BUDGET_FLOOR", str(DEFAULT_FLOOR))),
        help=f"refuse when core remaining < floor (default {DEFAULT_FLOOR})",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable stdout")
    parser.add_argument(
        "--wrap",
        nargs=argparse.REMAINDER,
        help="if budget ok, exec remaining args (use: -- wrap -- gh ...)",
    )
    args = parser.parse_args(argv)

    wrap = list(args.wrap or [])
    if wrap and wrap[0] == "--":
        wrap = wrap[1:]

    try:
        payload = fetch_rate_limit()
        core = core_resources(payload)
    except Exception as exc:
        _eprint(
            f"sugarbin: crime=github-api-budget-unmeasured detail={exc} "
            f"replacement=install/auth gh; cannot spend API without a budget reading"
        )
        return EXIT_MEASURE

    remaining = int(core.get("remaining", -1))
    limit = int(core.get("limit", -1))
    reset = int(core.get("reset", 0))
    reset_in = max(0, reset - int(time.time())) if reset else 0

    report = {
        "kind": "github-api-rate-budget",
        "resource": "core",
        "remaining": remaining,
        "limit": limit,
        "resetUnix": reset,
        "resetInSeconds": reset_in,
        "floor": args.floor,
        "status": "ok" if remaining >= args.floor else "low",
    }

    _eprint(
        f"sugarbin: gh-rate-budget phase=check resource=core "
        f"remaining={remaining} limit={limit} floor={args.floor} "
        f"reset_in_s={reset_in}"
    )

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(
            f"github-api-budget core remaining={remaining}/{limit} "
            f"floor={args.floor} reset_in_s={reset_in} status={report['status']}"
        )

    if remaining < args.floor:
        _eprint(
            f"sugarbin: crime=github-api-budget-low remaining={remaining} "
            f"floor={args.floor} reset_in_s={reset_in} "
            f"replacement=stop agent gh polling; autoscaler shares a user-scoped "
            f"budget until it has its own token (vault field autoscaler_pat / "
            f"GitHub App). Exit {EXIT_BUDGET}."
        )
        return EXIT_BUDGET

    if wrap:
        _eprint(f"sugarbin: gh-rate-budget phase=spend remaining={remaining} cmd={wrap[0]!r}")
        os.execvp(wrap[0], wrap)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
