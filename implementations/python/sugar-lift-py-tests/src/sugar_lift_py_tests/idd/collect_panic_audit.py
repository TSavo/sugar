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
from ..sugar_binary import SugarBinaryResolutionError, resolve_sugar_binary

RunCommand = Callable[[List[str], Path], CommandResult]
PackagePathResolver = Callable[[str], Path]
_CACHE_VERSION = "sugar-python-panic-audit-workspace-v2"


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
    sugar_bin: Optional[Path] = None,
) -> PanicAuditReport:
    root = root.resolve()
    runner = run_command or _run_command
    sugar = _resolve_audit_sugar_bin(sugar_bin)
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
        command = [os.fspath(sugar), "lift", "--report", "--visual", str(target.path)]
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
    """Resolve an installed import to a lift target path.

    Package modules (``numpy/__init__.py``) resolve to the package directory.
    Single-module libraries (stdlib ``statistics.py``) resolve to the module
    *file* — using the parent directory would audit the entire stdlib tree and
    produce false panics from unrelated modules (asyncio, inspect, …).

    ``decimal`` is special: the public ``decimal`` import is a thin reexport that
    prefers the C accelerator ``_decimal`` when present. Auditing
    ``decimal.__file__`` alone would lift only the try/import shim (false R=0)
    or, worse, never reach the pure-python body. Resolve to the pure-python
    implementation module ``_pydecimal`` (source file), never the C extension.
    """
    resolve_name = package
    if package == "decimal":
        # Public name stays "decimal" for axes/targets; body is _pydecimal.
        resolve_name = "_pydecimal"
    code = (
        "import importlib, os\n"
        f"mod = importlib.import_module({resolve_name!r})\n"
        "path = getattr(mod, '__file__', None)\n"
        "if path is None:\n"
        "    raise SystemExit('package has no __file__')\n"
        "path = os.path.abspath(path)\n"
        "base = os.path.basename(path)\n"
        "if base.endswith(('.so', '.pyd', '.dll')) or 'lib-dynload' in path:\n"
        "    raise SystemExit('refused C-extension path: ' + path)\n"
        "if base == '__init__.py':\n"
        "    print(os.path.dirname(path))\n"
        "else:\n"
        "    # Single-module file target (e.g. statistics.py / _pydecimal.py).\n"
        "    print(path)\n"
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
    if _is_visual_lift_command(command):
        target = Path(command[-1])
        audit_workspace = _cached_audit_workspace(target, cwd).workspace
        visual = _run_subprocess([*command[:-1], str(audit_workspace)], cwd)
        if visual.returncode == 0:
            return visual
        frontier_path = audit_workspace / ".sugar/panic-audit-frontier.json"
        frontier = _run_subprocess(
            [
                command[0],
                "lift",
                "--audit-frontier",
                "--allowed-broken-components",
                "python",
                "-o",
                str(frontier_path),
                str(audit_workspace),
            ],
            cwd,
        )
        if not frontier_path.is_file():
            return frontier
        try:
            payload = json.loads(frontier_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return frontier
        panics = payload.get("panics", []) if isinstance(payload, dict) else []
        messages = "\n".join(
            str(panic.get("reason") or panic.get("message") or "")
            for panic in panics
            if isinstance(panic, dict)
        )
        return CommandResult(frontier.returncode, messages, frontier.stderr)
    return _run_subprocess(command, cwd)


def _is_visual_lift_command(command: List[str]) -> bool:
    return len(command) >= 5 and command[1:4] == ["lift", "--report", "--visual"]


def _resolve_audit_sugar_bin(sugar_bin: Optional[Path]) -> Path:
    if sugar_bin is not None:
        return Path(sugar_bin)
    try:
        return resolve_sugar_binary()
    except SugarBinaryResolutionError as exc:
        raise RuntimeError(str(exc)) from exc


def _run_subprocess(command: List[str], cwd: Path) -> CommandResult:
    # ONE door: when sugar is invoked against a staged audit workspace, pin
    # SUGAR_HOME so ambient checkout/.sugar components cannot pollute the lift.
    env = _hermetic_env_for_sugar_command(command)
    try:
        completed = subprocess.run(
            command, cwd=cwd, text=True, capture_output=True, check=False, env=env
        )
    except FileNotFoundError as exc:
        return CommandResult(127, "", f"unable to execute {command[0]}: {exc}")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _hermetic_env_for_sugar_command(command: List[str]) -> dict:
    env = dict(os.environ)
    env.pop("SUGAR_COMPONENT_PATH", None)
    if len(command) < 2:
        return env
    # Prefer an explicit path arg that already stages `.sugar` (workspace),
    # scanning right-to-left so trailing workspace paths win over flags.
    for part in reversed(command[1:]):
        if not part or str(part).startswith("-"):
            continue
        candidate = Path(part)
        if candidate.is_dir() and (candidate / ".sugar").is_dir():
            from sugar_lift_py_tests.witness_harness import hermetic_sugar_env

            return hermetic_sugar_env(candidate, base=env)
    return env


def _prepare_audit_workspace(
    target: Path, root: Path, audit_workspace: Path, *, audit_only: bool = False
) -> None:
    target = target.resolve()
    root = root.resolve()
    audit_workspace.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        # Single-module library (e.g. stdlib statistics.py): stage the file
        # itself. Path.rglob on a file is empty — never silent-empty-workspace.
        if target.suffix != ".py":
            raise ValueError(f"audit target file must be a .py module, got {target}")
        destination = audit_workspace / target.name
        shutil.copy2(target, destination)
    else:
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
        _audit_manifest_toml(root, audit_only=audit_only),
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
    """Content-addressed cell for a panic-audit workspace.

    Keys on the installed package *tree* (so a numpy/pandas version bump that
    changes any hashed .py invalidates the cell), the audit config/manifest,
    and the Python kit sources that drive the lift. This is a legitimate
    content-addressed cache — not the mint/prove pool — and must NOT be
    isolated per-test; only rekeyed when its inputs change.
    """
    hasher = hashlib.sha256()
    _hash_text(hasher, "version", _CACHE_VERSION)
    _hash_text(hasher, "target-name", target.name)
    # Explicit package version when available so a same-tree metadata-only
    # bump still rekeys (belt + suspenders over the tree hash below).
    package_version = _installed_package_version(target)
    if package_version is not None:
        _hash_text(hasher, "package-version", package_version)
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


def _installed_package_version(target: Path) -> Optional[str]:
    """Best-effort version for an installed package directory (numpy/pandas)."""
    name = target.name
    if name.endswith(".py"):
        name = target.parent.name
    try:
        from importlib import metadata

        return metadata.version(name)
    except Exception:
        return None


def _hash_tree(hasher: Any, label: str, root: Path) -> None:
    _hash_text(hasher, f"{label}:root", root.name)
    if root.is_file():
        # Single-module target (statistics.py): hash the file itself.
        _hash_text(hasher, f"{label}:path", root.name)
        data = root.read_bytes()
        _hash_text(hasher, f"{label}:sha256", hashlib.sha256(data).hexdigest())
        return
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


def _audit_manifest_toml(root: Path, *, audit_only: bool = False) -> str:
    lift_rpc = (
        root
        / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py"
    )
    command = [
        sys.executable,
        str(lift_rpc),
        "--rpc",
    ]
    if audit_only:
        command.append("--audit-only")
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
