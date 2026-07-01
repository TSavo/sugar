from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from .command_result import CommandResult
from .extract_panic_records import extract_panic_records
from .lift_target import LiftTarget
from .panic_audit_report import PanicAuditReport
from .panic_record import PanicRecord


RunCommand = Callable[[List[str], Path], CommandResult]
PackagePathResolver = Callable[[str], Path]


def collect_panic_audit(
    root: Path,
    run_command: Optional[RunCommand] = None,
    *,
    installed_packages: Iterable[str] = (),
    package_path_resolver: Optional[PackagePathResolver] = None,
    include_showcases: bool = True,
) -> PanicAuditReport:
    root = root.resolve()
    runner = run_command or _run_command
    targets: list[LiftTarget] = []
    if include_showcases:
        targets.extend(
            (
                LiftTarget("numpy", root / "examples/numpy-showcase"),
                LiftTarget("pandas", root / "examples/pandas-showcase"),
            )
        )
    diagnostics: list[str] = []
    records: list[PanicRecord] = []
    resolver = package_path_resolver or _resolve_installed_package_path
    for package in installed_packages:
        try:
            package_path = resolver(package).resolve()
        except Exception as exc:  # pragma: no cover - exact exception is environment-owned
            target = LiftTarget(f"{package}-all", root)
            message = f"unable to resolve installed package `{package}`: {exc}"
            diagnostics.append(message)
            records.append(
                PanicRecord(
                    target=target.name,
                    kind="unexpected",
                    owner="idd.collect_panic_audit",
                    blame=package,
                    observed="package-resolution-failed",
                    requested="installed-package-path",
                    fix=f"install `{package}` in the audit interpreter or pass a resolver",
                    message=message,
                )
            )
            targets.append(target)
            continue
        targets.append(LiftTarget(f"{package}-all", package_path))
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
        command = ["sugar", "lift", "--report", "--visual", str(target.path)]
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
    return PanicAuditReport(targets=tuple(targets), records=records, diagnostics=diagnostics)


def _resolve_installed_package_path(package: str) -> Path:
    code = (
        "import importlib, os\n"
        f"mod = importlib.import_module({package!r})\n"
        "path = getattr(mod, '__file__', None)\n"
        "if path is None:\n"
        "    raise SystemExit('package has no __file__')\n"
        "print(os.path.dirname(os.path.abspath(path)))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail or f"import {package} failed")
    return Path(completed.stdout.strip())


def _run_command(command: List[str], cwd: Path) -> CommandResult:
    if command[:4] == ["sugar", "lift", "--report", "--visual"] and command:
        target = Path(command[-1])
        with tempfile.TemporaryDirectory(prefix="sugar-python-audit-") as tmp:
            audit_workspace = Path(tmp) / target.name
            _prepare_audit_workspace(target, cwd, audit_workspace)
            return _run_subprocess([*command[:-1], str(audit_workspace)], cwd)
    return _run_subprocess(command, cwd)


def _run_subprocess(command: List[str], cwd: Path) -> CommandResult:
    try:
        completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    except FileNotFoundError as exc:
        return CommandResult(127, "", f"unable to execute {command[0]}: {exc}")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _prepare_audit_workspace(target: Path, root: Path, audit_workspace: Path) -> None:
    target = target.resolve()
    root = root.resolve()
    audit_workspace.mkdir(parents=True, exist_ok=True)
    for source in sorted(target.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        relative = source.relative_to(target)
        destination = audit_workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    sugar_dir = audit_workspace / ".sugar"
    manifest_dir = sugar_dir / "lift/python"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (sugar_dir / "config.toml").write_text(
        "\n".join(
            [
                '[[plugins]]',
                'name = "python-audit-lift"',
                'kind = "lift"',
                'surface = "python"',
                'emit = "ir-document"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    lift_rpc = root / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py"
    command = [
        sys.executable,
        str(lift_rpc),
        "--rpc",
        "--audit-only",
    ]
    command_items = ", ".join(_toml_string(item) for item in command)
    (manifest_dir / "manifest.toml").write_text(
        "\n".join(
            [
                'name = "python-audit-lift"',
                'version = "0.1.0"',
                'protocol_version = "pep/1.7.0"',
                'kind = "lift"',
                f"command = [{command_items}]",
                f"working_dir = {_toml_string(str(root))}",
                "",
                "[capabilities]",
                'authoring_surfaces = ["python"]',
                'ir_version = "v1.1.0"',
                'emits_signed_mementos = false',
                "",
            ]
        ),
        encoding="utf-8",
    )


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
