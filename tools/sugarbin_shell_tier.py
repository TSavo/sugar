#!/usr/bin/env python3
"""Run and audit the nine sugarbin shell contracts enrolled in per-tip CI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


BATCHES = {
    "execution": [
        "tests/sugarbin_local_exec.sh",
        "tests/sugarbin_bx_exec.sh",
        "tests/sugarbin_docker_exec.sh",
    ],
    "guards": [
        "tests/sugarbin_mount_proof_guard.sh",
        "tests/sugarbin_docker_daemon_guard.sh",
        "tests/sugarbin_wrapper_compat.sh",
    ],
    "artifacts": [
        "tests/sugarbin_artifact_manifest.sh",
        "tests/sugarbin_build_identity_target.sh",
        "tests/sugarbin_build_root_identity.sh",
    ],
}
ROSTER = [contract for batch in BATCHES.values() for contract in batch]


def _body_path(reports_dir: Path, contract: str) -> Path:
    return reports_dir / f"{Path(contract).stem}.json"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _body(
    contract: str,
    *,
    commit: str,
    status: str,
    reason: str,
    exit_code: int | None = None,
    elapsed_seconds: float | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "measurementClass": "sugarbin-shell-contract",
        "contract": contract,
        "batch": next(name for name, rows in BATCHES.items() if contract in rows),
        "measuredCommit": commit,
        "status": status,
        "reason": reason,
        "exitCode": exit_code,
    }
    if elapsed_seconds is not None:
        payload["elapsedSeconds"] = round(elapsed_seconds, 3)
    return payload


def initialize(reports_dir: Path, *, commit: str) -> int:
    for contract in ROSTER:
        _write_json(
            _body_path(reports_dir, contract),
            _body(
                contract,
                commit=commit,
                status="unmeasured",
                reason="batch-not-started",
            ),
        )
    print(f"sugarbin-shell init roster={len(ROSTER)} absent={len(ROSTER)}")
    return 0


def run_batch(batch: str, *, repo: Path, reports_dir: Path, commit: str) -> int:
    failures = 0
    for contract in BATCHES[batch]:
        path = repo / contract
        body_path = _body_path(reports_dir, contract)
        print(f"ATTEND phase=start batch={batch} contract={contract}", flush=True)
        if not path.is_file():
            _write_json(
                body_path,
                _body(
                    contract,
                    commit=commit,
                    status="unmeasured",
                    reason="script-missing",
                ),
            )
            print(
                f"ATTEND phase=done batch={batch} contract={contract} "
                "status=unmeasured reason=script-missing",
                flush=True,
            )
            failures += 1
            continue

        _write_json(
            body_path,
            _body(
                contract,
                commit=commit,
                status="running",
                reason="command-started",
            ),
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                ["bash", str(path), str(repo)], cwd=repo, check=False
            )
        except OSError as error:
            elapsed = time.monotonic() - started
            _write_json(
                body_path,
                _body(
                    contract,
                    commit=commit,
                    status="unmeasured",
                    reason=f"launch-failed:{error}",
                    elapsed_seconds=elapsed,
                ),
            )
            print(
                f"ATTEND phase=done batch={batch} contract={contract} "
                f"status=unmeasured reason=launch-failed elapsed_s={elapsed:.3f}",
                flush=True,
            )
            failures += 1
            continue

        elapsed = time.monotonic() - started
        _write_json(
            body_path,
            _body(
                contract,
                commit=commit,
                status="completed",
                reason=f"exit-{completed.returncode}",
                exit_code=completed.returncode,
                elapsed_seconds=elapsed,
            ),
        )
        print(
            f"ATTEND phase=done batch={batch} contract={contract} "
            f"status=completed exit={completed.returncode} elapsed_s={elapsed:.3f}",
            flush=True,
        )
        if completed.returncode != 0:
            failures += 1
    return 1 if failures else 0


def _read_body(path: Path) -> tuple[dict[str, object] | None, str | None]:
    if not path.is_file():
        return None, "report-missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"report-invalid:{error}"
    if not isinstance(payload, dict):
        return None, "report-root-not-object"
    return payload, None


def audit(
    reports_dir: Path, *, receipt: Path, require_commit: str | None = None
) -> int:
    rows: list[dict[str, object]] = []
    crimes: list[str] = []
    attended = 0
    passed = 0
    failed = 0
    test_elapsed_seconds = 0.0

    for contract in ROSTER:
        payload, read_error = _read_body(_body_path(reports_dir, contract))
        if read_error is not None:
            row = {
                "contract": contract,
                "batch": next(
                    name for name, contracts in BATCHES.items() if contract in contracts
                ),
                "status": "unmeasured",
                "reason": read_error,
                "exitCode": None,
                "elapsedSeconds": None,
            }
            crimes.append(f"{contract}: {read_error}")
            rows.append(row)
            continue

        assert payload is not None
        reason: str | None = None
        if payload.get("measurementClass") != "sugarbin-shell-contract":
            reason = "measurement-class-mismatch"
        elif payload.get("contract") != contract:
            reason = "contract-mismatch"
        elif require_commit and payload.get("measuredCommit") != require_commit:
            reason = "commit-mismatch"

        status = payload.get("status")
        exit_code = payload.get("exitCode")
        elapsed_seconds = payload.get("elapsedSeconds")
        if isinstance(elapsed_seconds, (int, float)):
            test_elapsed_seconds += float(elapsed_seconds)
        if reason is not None:
            crimes.append(f"{contract}: {reason}")
            status = "unmeasured"
        elif status in ("running", "completed"):
            attended += 1
        if status == "completed" and exit_code == 0:
            passed += 1
        elif status == "completed":
            failed += 1

        row = {
            "contract": contract,
            "batch": payload.get("batch"),
            "status": status,
            "reason": reason or payload.get("reason"),
            "exitCode": exit_code,
            "elapsedSeconds": elapsed_seconds,
        }
        rows.append(row)

    absent = len(ROSTER) - attended
    summary = {
        "schemaVersion": 1,
        "measurementClass": "sugarbin-shell-tier-attendance",
        "measuredCommit": require_commit,
        "status": "complete" if attended == len(ROSTER) else "unmeasured",
        "roster": len(ROSTER),
        "attended": attended,
        "passed": passed,
        "failed": failed,
        "absent": absent,
        "testElapsedSeconds": round(test_elapsed_seconds, 3),
        "rows": rows,
    }
    _write_json(receipt, summary)

    print("### sugarbin shell tier attendance")
    print()
    print(f"- roster: `{len(ROSTER)}`")
    print(f"- attended: `{attended}`")
    print(f"- passed: `{passed}`")
    print(f"- failed: `{failed}`")
    print(f"- absent: `{absent}`")
    print(f"- measured test time: `{test_elapsed_seconds:.3f}s`")
    print()
    print("| batch | contract | status | reason |")
    print("| --- | --- | --- | --- |")
    for row in rows:
        print(
            f"| `{row['batch']}` | `{row['contract']}` | `{row['status']}` | "
            f"`{row['reason']}` |"
        )
    print()
    print(f"**R_sugarbin_shell_attendance = {absent}**")
    for crime in crimes:
        print(f"::error::{crime}", file=sys.stderr)
    return 0 if attended == len(ROSTER) and passed == len(ROSTER) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true")

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--reports-dir", type=Path, required=True)
    init_parser.add_argument("--commit", required=True)

    batch_parser = subparsers.add_parser("run-batch")
    batch_parser.add_argument("batch", choices=BATCHES)
    batch_parser.add_argument("--repo", type=Path, required=True)
    batch_parser.add_argument("--reports-dir", type=Path, required=True)
    batch_parser.add_argument("--commit", required=True)

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--reports-dir", type=Path, required=True)
    audit_parser.add_argument("--receipt", type=Path, required=True)
    audit_parser.add_argument("--require-commit")

    args = parser.parse_args(argv)
    if args.command == "list":
        if args.json:
            print(json.dumps(BATCHES, indent=2))
        else:
            for batch, contracts in BATCHES.items():
                for contract in contracts:
                    print(f"{batch}\t{contract}")
        return 0
    if args.command == "init":
        return initialize(args.reports_dir, commit=args.commit)
    if args.command == "run-batch":
        return run_batch(
            args.batch,
            repo=args.repo.resolve(),
            reports_dir=args.reports_dir,
            commit=args.commit,
        )
    if args.command == "audit":
        return audit(
            args.reports_dir,
            receipt=args.receipt,
            require_commit=args.require_commit,
        )
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
