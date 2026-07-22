"""Permanent baseline-free R_bare_exceptions floor."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "bare_exception_zero_tolerance.py"
_SPEC = importlib.util.spec_from_file_location(
    "bare_exception_zero_tolerance", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_planted_python_exception_trips_bare_floor() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "raise ValueError('planted bare exception')"],
        text=True,
        capture_output=True,
        check=False,
    )

    offender = _SCANNER.bare_exception_offender(
        file="planted.py", result=result
    )

    assert offender is not None
    assert offender.returncode == 1
    assert "ValueError: planted bare exception" in offender.stderr_tail
    assert _SCANNER.r_bare_exceptions([offender]) == 1


def test_typed_gap_testimony_is_not_bare() -> None:
    # An intentional typed source-tree gap (SugarNotWritten) is the sanctioned
    # ``typed-gap`` outcome -- distinct from a bare Python exception. Even with a
    # nonzero child exit, a typed-gap testimony is never a bare-exception
    # offender.
    result = subprocess.CompletedProcess(
        args=["child"],
        returncode=0,
        stdout=json.dumps({"kind": "lift-terminal", "outcome": "typed-gap"}),
        stderr="",
    )

    assert (
        _SCANNER.bare_exception_offender(file="typed-red.py", result=result)
        is None
    )


def test_signal_death_is_not_bare() -> None:
    result = subprocess.CompletedProcess(
        args=["child"], returncode=-6, stdout="", stderr="SIGABRT"
    )

    assert _SCANNER.bare_exception_offender(file="crash.py", result=result) is None


def test_production_roots_cover_package_and_corpus_tooling(tmp_path: Path) -> None:
    assert _SCANNER.production_roots(tmp_path) == (
        tmp_path
        / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        tmp_path / "implementations/python/sugar-lift-py-tests/scripts",
    )


def test_empty_surface_is_loud(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no Python source files"):
        _SCANNER.require_python_paths((tmp_path / "missing",))
