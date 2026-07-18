"""Permanent baseline-free R_timeouts floor."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "timeout_zero_tolerance.py"
_SPEC = importlib.util.spec_from_file_location("timeout_zero_tolerance", _SCANNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_planted_sleep_trips_timeout_floor() -> None:
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        subprocess.run(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=0.01,
            check=False,
        )

    offender = _SCANNER.timeout_offender(
        file="planted.py", timeout_seconds=raised.value.timeout
    )

    assert offender.file == "planted.py"
    assert _SCANNER.r_timeouts([offender]) == 1


def test_completed_child_is_not_timeout() -> None:
    assert _SCANNER.r_timeouts([]) == 0


def test_production_roots_cover_package_and_corpus_tooling(tmp_path: Path) -> None:
    assert _SCANNER.production_roots(tmp_path) == (
        tmp_path
        / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        tmp_path / "implementations/python/sugar-lift-py-tests/scripts",
    )


def test_empty_surface_is_loud(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no Python source files"):
        _SCANNER.require_python_paths((tmp_path / "missing",))
