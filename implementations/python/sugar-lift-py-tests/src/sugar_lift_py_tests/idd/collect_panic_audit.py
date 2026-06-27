from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, List, Optional

from .command_result import CommandResult
from .extract_panic_records import extract_panic_records
from .lift_target import LiftTarget
from .panic_audit_report import PanicAuditReport
from .panic_record import PanicRecord


RunCommand = Callable[[List[str], Path], CommandResult]


def collect_panic_audit(root: Path, run_command: Optional[RunCommand] = None) -> PanicAuditReport:
    root = root.resolve()
    runner = run_command or _run_command
    targets = (
        LiftTarget("numpy", root / "examples/numpy-showcase"),
        LiftTarget("pandas", root / "examples/pandas-showcase"),
    )
    diagnostics: list[str] = []
    records: list[PanicRecord] = []
    for target in targets:
        if not target.path.exists():
            message = f"missing target: {target.path}"
            diagnostics.append(message)
            records.append(
                PanicRecord(
                    target=target.name,
                    kind="unexpected",
                    owner="idd.collect_panic_audit",
                    blame=str(target.path),
                    observed="missing-target",
                    requested="audit target",
                    fix="create the numpy/pandas target or point the audit at the real target",
                    message=message,
                )
            )
            continue
        command = ["sugar", "lift", "--report", "--visual", "--audit-only", str(target.path)]
        result = runner(command, root)
        target_records = extract_panic_records(target, result.stdout, result.stderr)
        records.extend(target_records)
        if result.returncode != 0 and not target_records:
            message = f"{target.name} lift exited {result.returncode} without construction panic records"
            detail = (result.stderr or result.stdout).strip()
            if detail:
                message = f"{message}: {detail}"
            diagnostics.append(message)
            records.append(
                PanicRecord(
                    target=target.name,
                    kind="unexpected",
                    owner="idd.collect_panic_audit",
                    blame=str(target.path),
                    observed=f"exit={result.returncode}",
                    requested="construction-panic-records",
                    fix="make audit-only emit structured construction panic records",
                    message=message,
                )
            )
    return PanicAuditReport(targets=targets, records=records, diagnostics=diagnostics)


def _run_command(command: List[str], cwd: Path) -> CommandResult:
    try:
        completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    except FileNotFoundError as exc:
        return CommandResult(127, "", f"unable to execute {command[0]}: {exc}")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)
