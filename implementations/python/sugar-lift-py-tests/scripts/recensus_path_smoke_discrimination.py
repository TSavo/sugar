#!/usr/bin/env python3
"""Negative-arm discrimination for recensus-path-smoke teeth.

A tooth that has only ever been seen GREEN is not known to bite. This runner
plants one fault at a time via RECENSUS_PATH_SMOKE_LIE and OBSERVES the sealed
path verdict — not reasoned, not asserted from positive-arm silence.

Arms (binding):
  1. constructed_zero -> PATH_RED, failedTooth=known_constructed
  2. swallow_panic    -> PATH_RED, failedTooth=known_panic
  3. drop_opaque      -> PATH_RED, failedTooth=known_unconstructed
  4. crash_mid        -> PATH_UNMEASURED, failedTooth=crash_not_green
     (NOT green, NOT PATH_RED — crash-banks-measured / crash-prints-zero class)

Exit 0 only when every arm bites with the named tooth. CI must re-run this on
every commit; one-time human observation is not enrollment.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
_SMOKE = _SCRIPTS / "recensus_path_smoke.py"

# (lie, expected_verdict, expected_failed_tooth, expected_exit)
ARMS: list[tuple[str, str, str, int]] = [
    ("constructed_zero", "PATH_RED", "known_constructed", 1),
    ("swallow_panic", "PATH_RED", "known_panic", 1),
    ("drop_opaque", "PATH_RED", "known_unconstructed", 1),
    ("crash_mid", "PATH_UNMEASURED", "crash_not_green", 2),
]


def _run_arm(lie: str, out_dir: Path) -> tuple[int, dict[str, Any], float]:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["RECENSUS_PATH_SMOKE_LIE"] = lie
    env["RECENSUS_PATH_SMOKE_OUT"] = str(out_dir)
    env["PYTHONUNBUFFERED"] = "1"
    started = time.time()
    proc = subprocess.run(
        [sys.executable, "-u", str(_SMOKE)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.time() - started
    # Always surface the smoke log so a failed arm is debuggable in CI.
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n", flush=True)
    if proc.stderr:
        print(proc.stderr, end="" if proc.stderr.endswith("\n") else "\n", file=sys.stderr, flush=True)
    seal = out_dir / "path_verdict.json"
    body: dict[str, Any] = {}
    if seal.is_file():
        body = json.loads(seal.read_text(encoding="utf-8"))
    return proc.returncode, body, elapsed


def main() -> int:
    print(
        "PATH_SMOKE_DISC START arms="
        + ",".join(a[0] for a in ARMS)
        + " (negative arms must bite; green-only teeth are decoration)",
        flush=True,
    )
    rows: list[dict[str, Any]] = []
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="recensus-path-smoke-disc-") as tmp:
        base = Path(tmp)
        for lie, want_verdict, want_tooth, want_exit in ARMS:
            out = base / lie
            print(f"PATH_SMOKE_DISC arm={lie} status=start", flush=True)
            code, body, elapsed = _run_arm(lie, out)
            got_verdict = body.get("pathVerdict")
            got_tooth = body.get("failedTooth")
            row = {
                "lie": lie,
                "exit": code,
                "pathVerdict": got_verdict,
                "failedTooth": got_tooth,
                "elapsed_s": round(elapsed, 3),
                "want_verdict": want_verdict,
                "want_tooth": want_tooth,
                "want_exit": want_exit,
            }
            rows.append(row)
            ok = (
                code == want_exit
                and got_verdict == want_verdict
                and got_tooth == want_tooth
            )
            if ok:
                print(
                    f"PATH_SMOKE_DISC arm={lie} status=BITE "
                    f"verdict={got_verdict} tooth={got_tooth} "
                    f"exit={code} elapsed_s={elapsed:.2f}",
                    flush=True,
                )
            else:
                msg = (
                    f"arm={lie} expected verdict={want_verdict} tooth={want_tooth} "
                    f"exit={want_exit}; got verdict={got_verdict!r} tooth={got_tooth!r} "
                    f"exit={code} body_keys={sorted(body.keys())}"
                )
                failures.append(msg)
                print(f"PATH_SMOKE_DISC arm={lie} status=MISS {msg}", flush=True)

    # Bankable table (also lands in CI log as the discrimination evidence).
    print("", flush=True)
    print("| Arm | exit | pathVerdict | failedTooth | elapsed_s |", flush=True)
    print("| --- | --- | --- | --- | --- |", flush=True)
    for r in rows:
        print(
            f"| `{r['lie']}` | {r['exit']} | **{r['pathVerdict']}** | "
            f"**{r['failedTooth']}** | {r['elapsed_s']} |",
            flush=True,
        )
    print("", flush=True)

    if failures:
        print("PATH_SMOKE_DISC FAIL teeth did not all bite:", flush=True)
        for f in failures:
            print(f"  - {f}", flush=True)
        return 1

    print(
        "PATH_SMOKE_DISC PASS all four negative arms observed "
        "(PATH_RED x3 + PATH_UNMEASURED crash)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
