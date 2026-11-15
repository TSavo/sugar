"""Process floors must enter through the authenticated shared demand table."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
SCRIPTS = ROOT / "implementations/python/sugar-lift-py-tests/scripts"
FLOOR_SCRIPTS = (
    "native_crash_zero_tolerance.py",
    "bare_exception_zero_tolerance.py",
    "timeout_zero_tolerance.py",
)


def _load_runtime():
    path = SCRIPTS / "_enum_floor_runtime.py"
    spec = importlib.util.spec_from_file_location("enum_floor_runtime_tooth", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_demand_table_refuses_without_waiting_for_scan(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            str(path)
            for path in (
                ROOT / "tools",
                ROOT / "implementations/python/sugar-lift-py-tests/src",
                ROOT / "implementations/python/sugar-lift-python-source/src",
                ROOT / "implementations/python/sugar-source-tree/src",
            )
        ),
    }
    for script in FLOOR_SCRIPTS:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--repo-root", str(tmp_path)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 2, (script, result.stdout, result.stderr)
        assert "authenticated python-demand-table" in result.stdout
        assert "refusing local demand derivation" in result.stdout


def test_demand_table_helper_accepts_existing_file_and_rejects_missing(
    tmp_path: Path,
) -> None:
    runtime = _load_runtime()
    table = tmp_path / "python-demand-table.json"
    table.write_text("{}\n", encoding="utf-8")
    assert runtime.require_demand_table(table) == table.resolve()
    try:
        runtime.require_demand_table(tmp_path / "missing.json")
    except ValueError as error:
        assert "not a file" in str(error)
    else:
        raise AssertionError("missing demand table must refuse")


def test_all_process_floor_doors_forward_the_supplied_table() -> None:
    for script in FLOOR_SCRIPTS:
        source = (SCRIPTS / script).read_text(encoding="utf-8")
        assert "--demand-table-path" not in source or "add_demand_table_arg" in source
        assert "require_demand_table(args.demand_table_path)" in source
        assert "demand_table_path=demand_table_path" in source
        assert "scan_paths" in source


def test_only_silent_takes_no_demand_table() -> None:
    for script in FLOOR_SCRIPTS:
        assert "add_demand_table_arg" in (SCRIPTS / script).read_text()
    silent = (SCRIPTS / "silent_zero_tolerance.py").read_text()
    assert "add_demand_table_arg" not in silent
