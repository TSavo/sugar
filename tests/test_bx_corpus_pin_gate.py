"""Focused unit tests for tools/bx_corpus_pin_gate.py — no live pandas corpus.

Identity mode with --observed-* test doubles: pure comparison, no Mac open of
pandas, no battleaxe. Exit 78 on mismatch; exit 0 on match.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "bx_corpus_pin_gate.py"
EXIT_PIN = 78


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_identity_match_exit_0() -> None:
    r = _run(
        [
            "--expected-version",
            "3.0.3",
            "--expected-file-count",
            "1421",
            "--observed-version",
            "3.0.3",
            "--observed-file-count",
            "1421",
        ]
    )
    assert r.returncode == 0, r.stderr
    assert "phase=ok" in r.stderr
    assert "bx-corpus-pin-ok" in r.stdout


def test_wrong_version_exit_78() -> None:
    r = _run(
        [
            "--expected-version",
            "3.0.3",
            "--expected-file-count",
            "1421",
            "--observed-version",
            "2.3.3",
            "--observed-file-count",
            "1421",
        ]
    )
    assert r.returncode == EXIT_PIN, (r.returncode, r.stderr)
    assert "corpus-pin-mismatch" in r.stderr
    assert "2.3.3" in r.stderr


def test_wrong_file_count_exit_78() -> None:
    """Tonight's hole: system 1415 vs pin 1421."""
    r = _run(
        [
            "--expected-version",
            "3.0.3",
            "--expected-file-count",
            "1421",
            "--observed-version",
            "3.0.3",
            "--observed-file-count",
            "1415",
        ]
    )
    assert r.returncode == EXIT_PIN, (r.returncode, r.stderr)
    assert "file_count" in r.stderr
    assert "1415" in r.stderr


def test_system_python_combo_exit_78() -> None:
    """pandas 2.3.3 with 1415 files — the wrong corpus that almost shipped."""
    r = _run(
        [
            "--expected-version",
            "3.0.3",
            "--expected-file-count",
            "1421",
            "--observed-version",
            "2.3.3",
            "--observed-file-count",
            "1415",
        ]
    )
    assert r.returncode == EXIT_PIN
    assert "crime=corpus-pin-mismatch" in r.stderr


def test_banked_pin_file_loads_expected_identity() -> None:
    pin = ROOT / "docs" / "ledgers" / "pins" / "pandas-3.0.3.pin.json"
    assert pin.is_file(), "banked pin missing from checkout"
    # Need corpus_pin import path for load_pin.
    env_pythonpath = (
        f"{ROOT / 'implementations/python/sugar-lift-py-tests/src'}:"
        f"{ROOT / 'implementations/python/sugar-source-tree/src'}"
    )
    r = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--expected-pin",
            str(pin),
            "--observed-version",
            "3.0.3",
            "--observed-file-count",
            "1421",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": env_pythonpath},
    )
    assert r.returncode == 0, r.stderr
    assert "3.0.3" in r.stderr
    assert "1421" in r.stderr
