"""Permanent baseline-free R_native_crashes floor."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import pytest


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_KIT = sugar_lift_py_tests_package_root()
_SCANNER_PATH = _KIT / "scripts" / "native_crash_zero_tolerance.py"
_SPEC = importlib.util.spec_from_file_location(
    "native_crash_zero_tolerance", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_planted_abort_trips_native_crash_floor() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, signal; os.kill(os.getpid(), signal.SIGABRT)",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    offender = _SCANNER.native_crash_offender(
        file="planted.py",
        returncode=result.returncode,
        stderr=result.stderr,
    )

    assert offender is not None
    assert offender.signal == signal.Signals(signal.SIGABRT).name
    assert _SCANNER.r_native_crashes([offender]) == 1


def test_python_exception_is_not_a_native_crash() -> None:
    offender = _SCANNER.native_crash_offender(
        file="typed-red.py",
        returncode=3,
        stderr="ConstructionPanic",
    )

    assert offender is None


def test_success_is_not_a_native_crash() -> None:
    assert (
        _SCANNER.native_crash_offender(
            file="green.py",
            returncode=os.EX_OK,
            stderr="",
        )
        is None
    )


def test_production_roots_cover_package_and_corpus_tooling(tmp_path: Path) -> None:
    roots = _SCANNER.production_roots(tmp_path)

    assert roots == (
        tmp_path / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        tmp_path / "implementations/python/sugar-lift-py-tests/scripts",
    )


def test_empty_surface_is_loud(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no Python source files"):
        _SCANNER.require_python_paths((tmp_path / "missing",))
