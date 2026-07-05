from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional

from .command_result import CommandResult
from .extract_panic_records import extract_panic_records
from .lift_target import LiftTarget
from .panic_audit_report import PanicAuditReport
from .panic_record import PanicRecord

RunCommand = Callable[[List[str], Path], CommandResult]
PackagePathResolver = Callable[[str], Path]
_CACHE_VERSION = "sugar-python-panic-audit-workspace-v1"


@dataclass(frozen=True)
class CachedAuditWorkspace:
    workspace: Path
    cache_key: str
    hit: bool


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
        except (
            Exception
        ) as exc:  # pragma: no cover - exact exception is environment-owned
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
    return PanicAuditReport(
        targets=tuple(targets), records=records, diagnostics=diagnostics
    )


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
        audit_workspace = _cached_audit_workspace(target, cwd).workspace
        return _run_subprocess([*command[:-1], str(audit_workspace)], cwd)
    return _run_subprocess(command, cwd)


def _run_subprocess(command: List[str], cwd: Path) -> CommandResult:
    try:
        completed = subprocess.run(
            command, cwd=cwd, text=True, capture_output=True, check=False
        )
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
    (sugar_dir / "config.toml").write_text(_audit_config_toml(), encoding="utf-8")
    (manifest_dir / "manifest.toml").write_text(
        _audit_manifest_toml(root),
        encoding="utf-8",
    )


def _cached_audit_workspace(target: Path, root: Path) -> CachedAuditWorkspace:
    target = target.resolve()
    root = root.resolve()
    cache_key = _audit_workspace_cache_key(target, root)
    cell_root = _audit_workspace_cache_root() / cache_key
    workspace = cell_root / target.name
    metadata = cell_root / "audit-workspace.json"
    if _audit_workspace_cache_hit(metadata, workspace, cache_key):
        return CachedAuditWorkspace(workspace=workspace, cache_key=cache_key, hit=True)

    cache_root = _audit_workspace_cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    tmp_root = cache_root / f".{cache_key}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        _prepare_audit_workspace(target, root, tmp_root / target.name)
        metadata_payload = {
            "kind": "sugar-python-panic-audit-workspace",
            "version": _CACHE_VERSION,
            "cacheKey": cache_key,
            "targetName": target.name,
        }
        (tmp_root / "audit-workspace.json").write_text(
            json.dumps(metadata_payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            os.rename(tmp_root, cell_root)
        except FileExistsError:
            shutil.rmtree(tmp_root, ignore_errors=True)
        if not _audit_workspace_cache_hit(metadata, workspace, cache_key):
            raise RuntimeError(
                f"audit workspace cache cell {cell_root} was not materialized"
            )
        return CachedAuditWorkspace(workspace=workspace, cache_key=cache_key, hit=False)
    except Exception:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise


def _audit_workspace_cache_hit(metadata: Path, workspace: Path, cache_key: str) -> bool:
    if not metadata.is_file() or not workspace.is_dir():
        return False
    try:
        payload = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload.get("kind") == "sugar-python-panic-audit-workspace"
        and payload.get("version") == _CACHE_VERSION
        and payload.get("cacheKey") == cache_key
    )


def _audit_workspace_cache_key(target: Path, root: Path) -> str:
    hasher = hashlib.sha256()
    _hash_text(hasher, "version", _CACHE_VERSION)
    _hash_text(hasher, "target-name", target.name)
    _hash_text(hasher, "config", _audit_config_toml())
    _hash_text(hasher, "manifest", _audit_manifest_toml(root))
    _hash_tree(hasher, "target", target)
    _hash_tree(
        hasher,
        "python-kit",
        root / "implementations/python/sugar-lift-py-tests/src",
    )
    _hash_tree(
        hasher,
        "python-source-kit",
        root / "implementations/python/sugar-lift-python-source/src",
    )
    return hasher.hexdigest()


def _hash_tree(hasher: Any, label: str, root: Path) -> None:
    _hash_text(hasher, f"{label}:root", root.name)
    for source in sorted(root.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        relative = source.relative_to(root).as_posix()
        _hash_text(hasher, f"{label}:path", relative)
        data = source.read_bytes()
        _hash_text(hasher, f"{label}:sha256", hashlib.sha256(data).hexdigest())


def _hash_text(hasher: Any, label: str, value: str) -> None:
    hasher.update(label.encode("utf-8"))
    hasher.update(b"\0")
    hasher.update(value.encode("utf-8"))
    hasher.update(b"\0")


def _audit_workspace_cache_root() -> Path:
    configured = os.environ.get("SUGAR_PANIC_AUDIT_WORKSPACE_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "sugar" / "python-panic-audit-workspaces"


def _audit_config_toml() -> str:
    return "\n".join(
        [
            "[[plugins]]",
            'name = "python-audit-lift"',
            'kind = "lift"',
            'surface = "python"',
            'emit = "ir-document"',
            "",
        ]
    )


def _audit_manifest_toml(root: Path) -> str:
    lift_rpc = (
        root
        / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py"
    )
    command = [
        sys.executable,
        str(lift_rpc),
        "--rpc",
        "--audit-only",
    ]
    command_items = ", ".join(_toml_string(item) for item in command)
    return "\n".join(
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
            "emits_signed_mementos = false",
            "",
        ]
    )


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
